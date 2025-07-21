# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview
Red-A (红A) is a dividend arbitrage strategy analysis system for Chinese A-shares. It focuses on identifying high-dividend stocks and optimizing buy/sell timing around ex-dividend dates. The system uses BaoStock as the primary data source and requires no database infrastructure.

## Key Commands

### Environment Setup
```bash
# Create virtual environment and install dependencies
uv venv
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate     # Windows
uv pip sync pyproject.toml
```

### Main Workflow
```bash
# Run complete workflow (screening + backtest)
uv run main.py

# Screen only
uv run main.py --mode screen --years 5 --min-yield 6.0

# Backtest only (uses latest screening results)
uv run main.py --mode backtest

# Backtest with specific file
uv run main.py --mode backtest --csv dividend_screening_results_20240101_120000.csv
```


## Architecture Overview

### Data Flow
1. **BaoStock API** → `data_source.py` (unified data interface)
2. **Analysis** → `dividend.py` (yield calculations) + `screener.py` (stock filtering)
3. **Backtest** → `backtest.py` (strategy validation)
4. **Output** → CSV files and PNG charts

### Core Modules

- **data_source.py**: BaoStock data source wrapper
  - Unified API for all data fetching operations
  - Automatic login/logout management
  - Built-in caching to reduce API calls
  - Stock code format conversion
  - Forward adjustment calculations

- **dividend.py**: Dividend yield calculation module
  - Dynamic yield (past 12 months)
  - Static yield (specific year)
  - Comprehensive yield analysis
  - Thread-safe BaoStock operations

- **screener.py**: Stock screening engine
  - Filter stocks by dividend criteria
  - Support for Excel file input
  - Calculate multi-year average yields
  - Generate screening reports

- **backtest.py**: Backtesting engine
  - Test multiple entry timing strategies
  - Calculate returns with actual prices
  - Generate performance visualizations
  - Detailed trade-by-trade analysis

- **main.py**: Main entry point
  - Orchestrates screening and backtesting
  - Command-line interface
  - Automatic file management

### Strategy Implementation
The core strategy screens for:
- Stocks with >6% dividend yield for 5+ consecutive years
- Optimal entry: 7 days before ex-dividend date
- Exit: Maximum price within 3 trading days before ex-dividend date
- Target return: ~9.77% based on backtesting

### Output Files
The system generates:
- `dividend_screening_results_*.csv`: Stocks meeting criteria
- `dividend_backtest_results_*.csv`: Detailed trade records
- `dividend_backtest_summary_*.csv`: Strategy performance summary
- `dividend_backtest_results_*.png`: Visualization charts

## Development Notes

### Project Structure Principles
- Single responsibility per file
- Clear module boundaries
- No database dependencies
- Direct API data access

### Adding New Features
1. Extend `data_source.py` for new data types
2. Add analysis functions to appropriate modules
3. Update `main.py` to integrate new features

### Code Style
- Follow PEP 8 conventions
- Add type hints where appropriate
- Write comprehensive docstrings
- Use context managers for resource management