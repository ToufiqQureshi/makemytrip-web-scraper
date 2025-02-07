from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file
from flask_socketio import SocketIO, emit
import os
import threading
import yaml
import random
import logging
import time
import pandas as pd
from playwright.sync_api import sync_playwright
from datetime import datetime, timedelta
import re
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
load_dotenv()

# Proxy configuration
proxy_server = os.getenv("PROXY_SERVER")
proxy_username = os.getenv("PROXY_USERNAME")
proxy_password = os.getenv("PROXY_PASSWORD")

# Proxy pool
proxies = [
    {
        "server": proxy_server,
        "username": proxy_username,
        "password": proxy_password
    }
    # Add more proxies here if available
]

# Generate fake user agent
def get_fake_user_agent():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 6.1; Win64; x64; rv:105.0) Gecko/20100101 Firefox/105.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.5735.199 Safari/537.36 Edge/114.0.1823.67",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 12_3_1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.5672.126 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/112.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:100.0) Gecko/20100101 Firefox/100.0",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/111.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 6.3; Trident/7.0; AS; rv:11.0) like Gecko",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36"
    ]
    return random.choice(user_agents)

# Function to read URLs from the YAML file
def read_urls_from_yaml(file_path):
    try:
        with open(file_path, "r") as file:
            urls = yaml.safe_load(file)
        return urls
    except Exception as e:
        logging.error(f"Error reading URLs from YAML file: {e}")
        return {}

# Get dynamic dates for check-in and check-out
def get_dynamic_dates(offset):
    today = datetime.now()
    checkin_date = (today + timedelta(days=offset)).strftime("%m%d%Y")
    checkout_date = (today + timedelta(days=offset + 1)).strftime("%m%d%Y")
    return checkin_date, checkout_date

# Update static dates in URLs
def update_static_dates(urls, offset):
    checkin_date, checkout_date = get_dynamic_dates(offset)
    updated_urls = []
    for url in urls:
        url = re.sub(r"checkin=\d{8}", f"checkin={checkin_date}", url)
        url = re.sub(r"checkout=\d{8}", f"checkout={checkout_date}", url)
        updated_urls.append(url)
    return updated_urls

# Block unnecessary resources
def block_resources(route):
    blocked_resource_types = ["image", "stylesheet", "media", "font"]
    blocked_domains = ["google-analytics.com", "facebook.com", "doubleclick.net", "adservice.google.com"]
    request = route.request

    if request.resource_type in blocked_resource_types or any(domain in request.url for domain in blocked_domains):
        logging.info(f"Blocking resource: {request.url}")
        route.abort()
    else:
        route.continue_()

# Scrape data with retry and refresh logic
def scrape_data_wanted(page, url, data_count, retries=3):
    for attempt in range(retries):
        try:
            page.goto(url, wait_until="networkidle")

            # Simulate human-like behavior
            time.sleep(random.uniform(1, 3))

            # Scrape data (only required elements)
            scraped_data = {}
            columns = {
                "Hotel Name": ".wordBreak.appendRight10",
                "Hotel Price": "#hlistpg_hotel_shown_price",
                "Ratings": "#hlistpg_hotel_reviews_count",
            }

            # Check if "You Just Missed It" text is present on the page
            if page.query_selector('p.font14.appendBottom5.redText.latoBold.lineHight17'):
                # Hotel is sold out
                logging.info(f"Hotel sold out for URL: {url}")
                scraped_data["Hotel Price"] = "No inventory"
            else:
                # Scrape Hotel Price
                elements = page.query_selector_all(columns["Hotel Price"])
                if elements:
                    price_text = elements[0].inner_text().strip()
                    # Remove the ₹ symbol from the price if it exists
                    price_text = re.sub(r'[\₹]', '', price_text)  # Removes ₹ symbol
                    scraped_data["Hotel Price"] = price_text
                else:
                    scraped_data["Hotel Price"] = "N/A"

            # Scrape Score
            score_element = page.query_selector("#hlistpg_hotel_user_rating [itemprop='ratingValue']")
            if score_element:
                score_text = score_element.inner_text().strip()
                logging.info(f"Scraped score: {score_text}")
                scraped_data["Score"] = score_text
            else:
                logging.warning("Score element not found")
                scraped_data["Score"] = "N/A"

            # Scrape other fields
            for column, selector in columns.items():
                if column in ["Hotel Price", "Score"]:
                    continue  # Already handled
                elements = page.query_selector_all(selector)
                if elements:
                    scraped_data[column] = [el.inner_text().strip() for el in elements[:data_count]]
                else:
                    scraped_data[column] = "N/A"

            # Flatten lists if necessary
            for column in scraped_data:
                if isinstance(scraped_data[column], list) and len(scraped_data[column]) == 1:
                    scraped_data[column] = scraped_data[column][0]

            return scraped_data
        except Exception as e:
            logging.error(f"Error scraping {url} (attempt {attempt + 1}/{retries}): {e}")
            time.sleep(2)  # Adding delay before retry
    return None

# Save each group data to a separate sheet in an Excel file
def save_groups_to_excel(all_group_data):
    try:
        timestamp = datetime.now().strftime("%m%d%H%M")
        file_name = f"scraped_data_{timestamp}.xlsx"

        with pd.ExcelWriter(file_name, engine='xlsxwriter') as writer:
            for group_name, group_data in all_group_data.items():
                # Truncate the worksheet name to 31 characters
                truncated_name = group_name[:31]
                df = pd.DataFrame(group_data)

                # Ensure column order: Hotel Name, Hotel Price, others
                column_order = ["Hotel Name", "Hotel Price"] + [col for col in df.columns if col not in ["Hotel Name", "Hotel Price"]]
                df = df[column_order]

                df.to_excel(writer, sheet_name=truncated_name, index=False)
                logging.info(f"Group data saved to sheet: {truncated_name}")

        logging.info(f"All group data saved to {file_name}")
        return file_name
    except Exception as e:
        logging.error(f"Error saving group data to Excel: {e}")
        return None

# Get next proxy from the list for rotation
def get_next_proxy():
    return random.choice(proxies)

# Process a group of URLs in a single browser instance with proxy rotation
def process_group(group_id, urls, data_count, offset):
    try:
        with sync_playwright() as p:
            group_data = []
            hotel_name = None

            for url in urls:
                browser = p.chromium.launch(headless=False)  # Enable headless mode for better performance
                context = browser.new_context(
                    user_agent=get_fake_user_agent(),
                    viewport={"width": 1280, "height": 720},
                    proxy=get_next_proxy()  # Use random proxy from the list
                )
                context.route("**/*", block_resources)  # Apply resource blocking
                page = context.new_page()
                try:
                    updated_url = update_static_dates([url], offset)[0]
                    logging.info(f"Scraping URL: {updated_url}")

                    scraped_data = scrape_data_wanted(page, updated_url, data_count)
                    if scraped_data:
                        if not hotel_name:
                            hotel_name = scraped_data.get("Hotel Name", "Unknown_Hotel")
                        group_data.append(scraped_data)

                except Exception as e:
                    logging.error(f"Error processing URL {url}: {e}")
                finally:
                    page.close()
                    browser.close()

            logging.info(f"Finished scraping group: {group_id}")

            return {f"Group_{group_id}_{hotel_name}": group_data}

    except Exception as e:
        logging.error(f"Error in processing group {group_id}: {e}")
        return {}

# Main function to process all groups
def main(yaml_file_path, data_count, offset, max_threads=5):
    urls_data = read_urls_from_yaml(yaml_file_path)
    if not urls_data:
        logging.error("No URLs found in YAML file.")
        return

    all_group_data = {}
    with ThreadPoolExecutor(max_workers=max_threads) as executor:
        futures = []
        for group_id, urls in urls_data.items():
            futures.append(executor.submit(process_group, group_id, urls, data_count, offset))

        # Wait for all tasks to complete and collect data
        for future in futures:
            group_data = future.result()
            if group_data:
                all_group_data.update(group_data)

    # Save all group data to an Excel file with separate sheets
    if all_group_data:
        file_name = save_groups_to_excel(all_group_data)
        return file_name
    return None

# Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['ALLOWED_EXTENSIONS'] = {'yaml', 'yml'}
socketio = SocketIO(app)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            return redirect(request.url)
        if file and allowed_file(file.filename):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(file_path)
            data_count = int(request.form['data_count'])
            offset = int(request.form['offset'])
            threading.Thread(target=start_scraping, args=(file_path, data_count, offset)).start()
            return render_template('index.html', message="Scraping started. Please wait for the process to complete.")
    return render_template('index.html')

def start_scraping(file_path, data_count, offset):
    file_name = main(file_path, data_count, offset)
    if file_name:
        logging.info(f"Scraping completed. Data saved to {file_name}")
        socketio.emit('scraping_complete', {'message': 'Scraping completed.', 'file_name': file_name})
    else:
        logging.error("Scraping failed.")
        socketio.emit('scraping_complete', {'message': 'Scraping failed.'})

@app.route('/download/<filename>')
def download_file(filename):
    return send_file(filename, as_attachment=True)

@socketio.on('connect')
def handle_connect():
    emit('message', {'data': 'Connected'})

if __name__ == '__main__':
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    socketio.run(app, debug=True)