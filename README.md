# LeetCode Web Scraper

A Flask-based web application for scraping LeetCode problem data.

## Setup

1. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Run the application:
```bash
python app.py
```

4. Open your browser and navigate to `http://localhost:5000`

## Features

- Scrapes LeetCode problem data
- Displays problems in a clean, responsive UI
- Error handling and loading states

## Note

This is a basic implementation. LeetCode's website structure might change, which could affect the scraping functionality. You might need to update the selectors in `app.py` accordingly.

## Dependencies

- Flask
- requests
- beautifulsoup4
- python-dotenv 