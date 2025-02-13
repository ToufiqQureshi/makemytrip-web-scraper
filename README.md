# Flask Web Scraper

## Overview
This is a Flask-based web scraper that uses Playwright to extract hotel pricing and availability data from provided URLs. The application supports proxy rotation, dynamic date updates, and automatic resource blocking for efficiency.

## Features
- Proxy rotation and user-agent spoofing
- Dynamic date modification in URLs
- Multi-threaded scraping with Playwright
- Data export to Excel with multiple sheets
- Flask API for data scraping and retrieval
- WebSocket integration for real-time updates

## Installation
1. Clone the repository:
   \\\ash
   git clone <repository-url>
   cd <repository-folder>
   \\\
2. Create a virtual environment and install dependencies:
   \\\ash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   pip install -r requirements.txt
   \\\
3. Set up environment variables:
   Create a \.env\ file and define:
   \\\
   PROXY_SERVER=<your_proxy_server>
   PROXY_USERNAME=<your_proxy_username>
   PROXY_PASSWORD=<your_proxy_password>
   \\\

## Usage
1. Start the Flask app:
   \\\ash
   python app.py
   \\\
2. Upload a YAML file containing URLs to scrape.
3. View and download the scraped data.

## API Endpoints
- \/upload\: Upload YAML file
- \/scrape\: Start scraping process
- \/download\: Download scraped data

## Dependencies
- Flask
- Playwright
- Pandas
- PyYAML
- Dotenv

## License
MIT License
# makemytrip-web-scraper
