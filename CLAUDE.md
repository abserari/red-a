# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Red-A (红A) is a dividend arbitrage strategy analysis system for Chinese A-shares. It focuses on identifying high-dividend stocks and optimizing buy/sell timing around ex-dividend dates.

## Key Commands

### Environment Setup
```bash
# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate     # Windows
uv pip sync pyproject.toml

# Start MongoDB (required for data storage)
docker-compose up -d
```

### Data Acquisition
```bash
# Quick test with sample stocks (8 years data)
uv run get_data.py

# Sequential data acquisition with smart caching (RECOMMENDED)
# Default: 8 years of data, 0.5s delay between stocks
uv run get_data_sequential.py

# Force update all data (ignore cache)
uv run get_data_sequential.py --force

# Test mode (only first 20 stocks)
uv run get_data_sequential.py --test

# Custom parameters examples
uv run get_data_sequential.py --years 10  # 10 years of data
uv run get_data_sequential.py --delay 1.0  # 1 second delay
uv run get_data_sequential.py --dividend-days 7  # Update dividends weekly

# Single stock data acquisition example
uv run data_acquisition.py
```

### Analysis
```bash
# Launch Jupyter for strategy analysis
jupyter lab
# Open dividend_strategy_analysis.ipynb
```

### Testing
```bash
# Run tests (when implemented)
uv run tests/
```

## Architecture Overview

### Data Flow
1. **Data Sources** → `data_acquisition.py` or `tushare_data_acquisition.py`
2. **Storage** → MongoDB (stocks, daily_prices, dividends collections)
3. **Analysis** → `dividend_strategy.py` functions
4. **Visualization** → Jupyter notebooks

### Core Modules

- **data_acquisition.py**: Primary data fetcher with multiple data sources
  - Supports AkShare, BaoStock, and Tushare APIs
  - `get_stock_list()`: Fetches all A-share stock codes
  - `get_stock_history_smart()`: Intelligently fetches only missing data
  - `get_dividend_history()`: Retrieves dividend announcements with caching
  - MongoDB integration with automatic indexing and upsert logic

- **get_data_sequential.py**: Sequential data acquisition (stable & recommended)
  - Processes stocks one by one with configurable delay
  - Smart caching: skips stocks with complete data
  - Detailed progress tracking and ETA estimation
  - Robust error handling without complexity

- **dividend_strategy.py**: Strategy analysis functions
  - Calculate dividend yields
  - Find optimal entry/exit points
  - Backtest performance metrics

### Database Schema
MongoDB collections:
- `stocks`: Stock metadata (code, name)
- `daily_prices`: Historical OHLCV data with forward adjustment
- `dividends`: Dividend announcement records
- `tasks`: Data acquisition task tracking

### Strategy Implementation
The core strategy screens for:
- Stocks with >6% dividend yield for 5+ consecutive years
- Optimal entry: 7 days before ex-dividend date
- Exit: On or before ex-dividend date
- Target return: ~9.77% based on backtesting

**Note**: Default data acquisition fetches 8 years of historical data to ensure:
- Sufficient data for identifying 5+ years of consecutive high dividends
- Extra years for backtesting and validation
- Buffer for stocks that may have missing data in certain periods

## Development Notes

### Adding New Data Sources
Extend `data_acquisition.py` pattern - implement functions for:
1. Data fetching with retry logic
2. MongoDB storage with proper indexes
3. Progress tracking for batch operations

### Extending Strategy Analysis
Add new analysis functions to `dividend_strategy.py`:
- Follow existing patterns for date handling
- Include comprehensive docstrings
- Return pandas DataFrames for easy integration

### Data Update Patterns
The system uses intelligent incremental updates:
- Check existing data before fetching
- Only request missing date ranges
- Update task tracking for resumable operations