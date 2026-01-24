# CustomCRM

A lightweight, unified CRM system for Product Pricing and Quotation management.

## Project Structure

- `pricing_app/`: Management of products, categories, base costs, and price calculation logic.
- `quotation_app/`: Professional offer generation, PDF export, and client management.
- `shared/`: Shared configuration and database utilities.
- `static/`: Unified CSS and global assets.

## Features

- **Dynamic Pricing**: Automatic rounding and margin calculations with color-coded profit visualization.
- **Offer Generation**: Real-time NBS exchange rate fetching and professional PDF generation.
- **Unified UI**: Consistent dark-mode aesthetic with card-based layouts across all modules.
- **Portability**: Built with Flask and SQLite for easy deployment.

## Quick Start

1. Install dependencies: `pip install -r requirements.txt`
2. Run Pricing App: `python pricing_app/app.py` (Default: port 5000)
3. Run Quotation App: `python quotation_app/app.py` (Default: port 5001)

## Tech Stack
- **Backend**: Flask (Python)
- **Frontend**: Vanilla CSS / JavaScript
- **Database**: SQLite
- **PDF Export**: WeasyPrint
