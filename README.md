# OSRS Deadman Mode Scanner

A real-time market scanner for Old School RuneScape Deadman Mode that detects wash trades, identifies money-making opportunities, and finds arbitrage flips.

![Python](https://img.shields.io/badge/Python-3.6+-blue)
![License](https://img.shields.io/badge/License-MIT-green)

## Features

### Wash Trade Detection
- Monitors suspicious high-value trades (>1M gp at >1000x alch ratio)
- Tracks repeat patterns and sightings
- Two-tier alert system (red: >10M, yellow: >1M)
- Excludes legitimate rare gear (Twisted Bow, Scythe, etc.)

### Money Making Scanner
- Identifies NPC shop items with profitable GE markups
- Calculates daily profit potential
- Heat scoring based on trade recency

### High Alch Arbitrage
- Finds items profitable to buy and alch
- Accounts for nature rune costs
- Filter by stackable items or high liquidity

### Bid-Ask Spread Flipping
- Identifies GE price spreads (>10% margin)
- Flip score ranking (spread x volume)
- Best opportunities for margin trading

## Installation

```bash
git clone https://github.com/Lattixe/osrs-dmm-scanner.git
cd osrs-dmm-scanner
pip install -r requirements.txt
```

## Quick Start

**Windows:**
```bash
launch_scanner.bat
```

**Manual:**
```bash
python dmm_scanner.py
```

Then open http://localhost:5000 in your browser.

## Dashboard

| Tab | Description |
|-----|-------------|
| **Wash Trades** | Suspicious price manipulation alerts |
| **Money Making** | NPC shop to GE flip opportunities |
| **Arbitrage** | High Alch profits & bid-ask spreads |

### Controls
- Click column headers to sort
- Star items to favorite (persists in browser)
- Toggle light/dark mode
- Pause/Resume scanning

## Configuration

Edit constants at the top of `dmm_scanner.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `POLL_INTERVAL` | 30 | Seconds between API polls |
| `VOLUME_THRESHOLD` | 500 | Max daily volume for wash trade monitoring |
| `RATIO_THRESHOLD` | 1000 | Min price/alch ratio for alerts |
| `PRICE_THRESHOLD` | 1000000 | Min trade price (1M gp) |

## API

Data sourced from the [OSRS Wiki Real-Time Prices API](https://oldschool.runescape.wiki/w/RuneScape:Real-time_Prices) (DMM endpoint).

## License

MIT License - See LICENSE file for details.

## Disclaimer

This tool is for informational purposes only. Use at your own risk. Not affiliated with Jagex.
