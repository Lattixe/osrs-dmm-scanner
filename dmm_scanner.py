import json
import os
import sys
import time
import threading
from datetime import datetime
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import requests

# Force unbuffered stdout so output appears immediately when piped
sys.stdout.reconfigure(line_buffering=True)

# Enable ANSI escape codes on Windows
if os.name == "nt":
    os.system("")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://prices.runescape.wiki/api/v1/dmm"
HEADERS = {"User-Agent": "dmm-scanner - wash trade detector"}

POLL_INTERVAL = 30  # seconds (API data updates slowly, no need to hammer it)
MAX_ALERTS = 500  # cap stored alerts to prevent memory growth
VOLUME_THRESHOLD = 500  # max 24h total volume
RATIO_THRESHOLD = 1_000  # min price / alch ratio
PRICE_THRESHOLD = 1_000_000  # min trade price (1M gp)
HIGH_VALUE_THRESHOLD = 10_000_000  # extreme alert tier (10M gp)
DEDUP_WINDOW = 300  # seconds — same item+price within 5min = dedup

# Money making scanner thresholds
MM_MARKUP_THRESHOLD = 3  # min GE price / NPC value ratio
MM_MIN_VOLUME = 1  # must have actual trades

# Arbitrage scanner thresholds
NATURE_RUNE_COST = 200  # approx cost for alch calculations
MIN_ALCH_PROFIT = 100   # minimum profit per item to show
MIN_SPREAD_PCT = 10     # minimum spread % to show (10 = 10%)
MIN_FLIP_VOLUME = 50    # minimum 24h volume for flip opportunities

WEB_PORT = 5000

# ---------------------------------------------------------------------------
# NPC shop allowlist – only items genuinely purchasable from NPCs for GP
# ---------------------------------------------------------------------------

NPC_SHOP_ITEMS = {
    # General store basics
    "Pot", "Jug", "Bucket", "Tinderbox", "Hammer", "Chisel", "Shears",
    "Bowl", "Cake tin", "Knife", "Spade", "Candle", "Needle", "Thread",
    "Watering can",
    # Runes
    "Air rune", "Water rune", "Earth rune", "Fire rune", "Mind rune",
    "Body rune", "Chaos rune", "Death rune", "Nature rune", "Law rune",
    "Cosmic rune", "Astral rune", "Blood rune", "Soul rune", "Wrath rune",
    # Food shops
    "Bread", "Raw beef", "Raw chicken", "Pot of flour", "Jug of water",
    "Chocolate bar", "Grapes", "Pie dish", "Redberry pie", "Cake",
    "Pineapple",
    # Weapons & armor
    "Bronze dagger", "Bronze sword", "Bronze scimitar", "Bronze axe",
    "Bronze pickaxe", "Bronze med helm", "Bronze chainbody", "Bronze kiteshield",
    "Iron dagger", "Iron scimitar", "Iron axe", "Iron med helm", "Iron chainbody",
    "Steel dagger", "Steel scimitar", "Steel axe", "Steel med helm",
    "Steel chainbody", "Mithril dagger", "Mithril scimitar", "Mithril axe",
    # Arrows
    "Bronze arrow", "Iron arrow", "Steel arrow", "Mithril arrow",
    "Adamant arrow", "Rune arrow",
    # Leather & wizard gear
    "Leather body", "Leather gloves", "Leather boots", "Leather cowl",
    "Leather chaps", "Leather vambraces", "Studded body", "Studded chaps",
    "Wizard hat", "Blue wizard hat", "Blue wizard robe",
    # Staves
    "Staff of air", "Staff of water", "Staff of earth", "Staff of fire",
    "Battlestaff",
    # Herblore & crafting
    "Vial", "Vial of water", "Eye of newt", "Pestle and mortar",
    "Molten glass", "Ball of wool", "Bucket of sand", "Soda ash",
    "Glassblowing pipe", "Empty fishbowl", "Bronze bar",
    # Fishing
    "Feather", "Fishing bait",
    # Construction
    "Saw", "Limestone brick",
    # Slayer equipment
    "Broad bolts", "Broad arrows", "Enchanted gem", "Nose peg", "Earmuffs",
    "Face mask", "Slayer staff", "Mirror shield", "Bag of salt",
    "Rock hammer", "Rock thrownhammer", "Witchwood icon", "Insect repellent",
    "Leaf-bladed spear",
    # Shields
    "Anti-dragon shield", "Wooden shield",
    # Jewelry from shops
    "Amulet of magic", "Amulet of strength", "Amulet of power",
    "Phoenix necklace", "Brass necklace", "Gold necklace", "Gold ring",
    "Tiara",
    # Clothing
    "Red cape", "Blue cape", "Black cape", "Yellow cape",
    "Priest gown", "Desert shirt", "Desert robe",
    # Misc
    "Rope", "Silk", "Spice", "Chronicle", "Empty pot", "Empty jug",
    "Empty bucket",
}

# ---------------------------------------------------------------------------
# Wash trade exclusions – legitimate rare gear (not wash trade vehicles)
# ---------------------------------------------------------------------------

WASH_TRADE_EXCLUSIONS = {
    # Rare weapons
    "The Dogsword", "Thunder Khopesh", "Soulreaper axe", "Tumeken's shadow",
    "Scythe of vitur", "Twisted bow", "Zaryte crossbow", "Osmumten's fang",
    "Dragon claws", "Elder maul", "Inquisitor's mace", "Ghrazi rapier",
    "Blade of saeldor", "Voidwaker",
    # Mage gear
    "Mage's book", "Kodai wand", "Harmonised nightmare staff",
    "Volatile nightmare staff", "Eldritch nightmare staff",
    "Ancestral hat", "Ancestral robe top", "Ancestral robe bottom",
    "Tormented bracelet", "Elidinis' ward",
    # Range gear
    "Twisted buckler", "Armadyl crossbow", "Dragon hunter crossbow",
    "Pegasian boots", "Necklace of anguish", "Armadyl helmet",
    "Armadyl chestplate", "Armadyl chainskirt",
    # Melee gear
    "Avernic defender", "Primordial boots", "Amulet of torture",
    "Bandos chestplate", "Bandos tassets", "Ferocious gloves",
    "Infernal cape", "Bandos boots",
    # Spirit shields
    "Dragonfire shield", "Spectral spirit shield",
    "Arcane spirit shield", "Elysian spirit shield",
    # Justiciar
    "Justiciar faceguard", "Justiciar chestguard", "Justiciar legguards",
    # Masori
    "Masori mask", "Masori body", "Masori chaps",
    "Masori mask (f)", "Masori body (f)", "Masori chaps (f)",
    # Torva
    "Torva full helm", "Torva platebody", "Torva platelegs",
    # Inquisitor
    "Inquisitor's great helm", "Inquisitor's hauberk", "Inquisitor's plateskirt",
}

# ---------------------------------------------------------------------------
# NPC shop wiki URLs – maps item name → wiki shop page path
# ---------------------------------------------------------------------------

NPC_SHOP_URLS = {
    # General store basics → Lumbridge General Store
    "Pot": "Lumbridge_General_Store",
    "Jug": "Lumbridge_General_Store",
    "Bucket": "Lumbridge_General_Store",
    "Tinderbox": "Lumbridge_General_Store",
    "Hammer": "Lumbridge_General_Store",
    "Chisel": "Lumbridge_General_Store",
    "Shears": "Lumbridge_General_Store",
    "Bowl": "Lumbridge_General_Store",
    "Cake tin": "Lumbridge_General_Store",
    "Knife": "Lumbridge_General_Store",
    "Spade": "Lumbridge_General_Store",
    "Candle": "Lumbridge_General_Store",
    "Needle": "Lumbridge_General_Store",
    "Thread": "Lumbridge_General_Store",
    "Watering can": "Lumbridge_General_Store",
    # Runes → various rune shops
    "Air rune": "Aubury's_Rune_Shop.",
    "Water rune": "Aubury's_Rune_Shop.",
    "Earth rune": "Aubury's_Rune_Shop.",
    "Fire rune": "Aubury's_Rune_Shop.",
    "Mind rune": "Aubury's_Rune_Shop.",
    "Body rune": "Aubury's_Rune_Shop.",
    "Chaos rune": "Aubury's_Rune_Shop.",
    "Death rune": "Aubury's_Rune_Shop.",
    "Nature rune": "Aubury's_Rune_Shop.",
    "Law rune": "Aubury's_Rune_Shop.",
    "Cosmic rune": "Lundail's_Arena-side_Rune_Shop",
    "Astral rune": "Baba_Yaga's_Magic_Shop",
    "Blood rune": "Ali's_Discount_Wares",
    "Soul rune": "Ali's_Discount_Wares",
    "Wrath rune": "Justine's_stuff_for_the_Last_Shopper_Standing",
    # Food shops → Wydin's Food Store
    "Bread": "Wydin's_Food_Store",
    "Raw beef": "Wydin's_Food_Store",
    "Raw chicken": "Wydin's_Food_Store",
    "Pot of flour": "Wydin's_Food_Store",
    "Jug of water": "Wydin's_Food_Store",
    "Chocolate bar": "Wydin's_Food_Store",
    "Grapes": "Wydin's_Food_Store",
    "Pie dish": "Wydin's_Food_Store",
    "Redberry pie": "Wydin's_Food_Store",
    "Cake": "Wydin's_Food_Store",
    "Pineapple": "Wydin's_Food_Store",
    # Weapons & armor
    "Bronze dagger": "Varrock_Swordshop",
    "Bronze sword": "Varrock_Swordshop",
    "Bronze scimitar": "Zeke's_Superior_Scimitars",
    "Bronze axe": "Bob's_Brilliant_Axes",
    "Bronze pickaxe": "Nurmof's_Pickaxe_Shop",
    "Bronze med helm": "Peksa's_Helmet_Shop",
    "Bronze chainbody": "Wayne's_Chains",
    "Bronze kiteshield": "Cassie's_Shield_Shop",
    "Iron dagger": "Varrock_Swordshop",
    "Iron scimitar": "Zeke's_Superior_Scimitars",
    "Iron axe": "Bob's_Brilliant_Axes",
    "Iron med helm": "Peksa's_Helmet_Shop",
    "Iron chainbody": "Wayne's_Chains",
    "Steel dagger": "Varrock_Swordshop",
    "Steel scimitar": "Zeke's_Superior_Scimitars",
    "Steel axe": "Bob's_Brilliant_Axes",
    "Steel med helm": "Peksa's_Helmet_Shop",
    "Steel chainbody": "Wayne's_Chains",
    "Mithril dagger": "Varrock_Swordshop",
    "Mithril scimitar": "Zeke's_Superior_Scimitars",
    "Mithril axe": "Bob's_Brilliant_Axes",
    # Arrows → Lowe's Archery Emporium
    "Bronze arrow": "Lowe's_Archery_Emporium",
    "Iron arrow": "Lowe's_Archery_Emporium",
    "Steel arrow": "Lowe's_Archery_Emporium",
    "Mithril arrow": "Lowe's_Archery_Emporium",
    "Adamant arrow": "Lowe's_Archery_Emporium",
    "Rune arrow": "Lowe's_Archery_Emporium",
    # Leather & wizard gear
    "Leather body": "Fancy_Clothes_Store",
    "Leather gloves": "Fancy_Clothes_Store",
    "Leather boots": "Fancy_Clothes_Store",
    "Leather cowl": "Fancy_Clothes_Store",
    "Leather chaps": "Fancy_Clothes_Store",
    "Leather vambraces": "Fancy_Clothes_Store",
    "Studded body": "Fancy_Clothes_Store",
    "Studded chaps": "Fancy_Clothes_Store",
    "Wizard hat": "Betty's_Magic_Emporium",
    "Blue wizard hat": "Betty's_Magic_Emporium",
    "Blue wizard robe": "Betty's_Magic_Emporium",
    # Staves → Zaff's Superior Staffs!
    "Staff of air": "Zaff's_Superior_Staffs!",
    "Staff of water": "Zaff's_Superior_Staffs!",
    "Staff of earth": "Zaff's_Superior_Staffs!",
    "Staff of fire": "Zaff's_Superior_Staffs!",
    "Battlestaff": "Zaff's_Superior_Staffs!",
    # Herblore & crafting
    "Vial": "Aemad's_Adventuring_Supplies",
    "Vial of water": "Aemad's_Adventuring_Supplies",
    "Eye of newt": "Betty's_Magic_Emporium",
    "Pestle and mortar": "Aemad's_Adventuring_Supplies",
    "Molten glass": "Razmire_General_Store",
    "Ball of wool": "Lumbridge_General_Store",
    "Bucket of sand": "Razmire_General_Store",
    "Soda ash": "Razmire_General_Store",
    "Glassblowing pipe": "Razmire_General_Store",
    "Empty fishbowl": "Razmire_General_Store",
    "Bronze bar": "Razmire_General_Store",
    # Fishing → Gerrant's Fishy Business
    "Feather": "Gerrant's_Fishy_Business",
    "Fishing bait": "Gerrant's_Fishy_Business",
    # Construction → Razmire Builders Merchants
    "Saw": "Razmire_Builders_Merchants",
    "Limestone brick": "Razmire_Builders_Merchants",
    # Slayer equipment → Slayer Equipment (store)
    "Broad bolts": "Slayer_Equipment_(store)",
    "Broad arrows": "Slayer_Equipment_(store)",
    "Enchanted gem": "Slayer_Equipment_(store)",
    "Nose peg": "Slayer_Equipment_(store)",
    "Earmuffs": "Slayer_Equipment_(store)",
    "Face mask": "Slayer_Equipment_(store)",
    "Slayer staff": "Slayer_Equipment_(store)",
    "Mirror shield": "Slayer_Equipment_(store)",
    "Bag of salt": "Slayer_Equipment_(store)",
    "Rock hammer": "Slayer_Equipment_(store)",
    "Rock thrownhammer": "Slayer_Equipment_(store)",
    "Witchwood icon": "Slayer_Equipment_(store)",
    "Insect repellent": "Slayer_Equipment_(store)",
    "Leaf-bladed spear": "Slayer_Equipment_(store)",
    # Shields
    "Anti-dragon shield": "Oziach_(shop)",
    "Wooden shield": "Cassie's_Shield_Shop",
    # Jewelry from shops → Davon's Amulet Store
    "Amulet of magic": "Davon's_Amulet_Store",
    "Amulet of strength": "Davon's_Amulet_Store",
    "Amulet of power": "Davon's_Amulet_Store",
    "Phoenix necklace": "Davon's_Amulet_Store",
    "Brass necklace": "Davon's_Amulet_Store",
    "Gold necklace": "Davon's_Amulet_Store",
    "Gold ring": "Davon's_Amulet_Store",
    "Tiara": "Davon's_Amulet_Store",
    # Clothing
    "Red cape": "Thessalia's_Fine_Clothes",
    "Blue cape": "Thessalia's_Fine_Clothes",
    "Black cape": "Thessalia's_Fine_Clothes",
    "Yellow cape": "Thessalia's_Fine_Clothes",
    "Priest gown": "Thessalia's_Fine_Clothes",
    "Desert shirt": "Shantay_Pass_Shop",
    "Desert robe": "Shantay_Pass_Shop",
    # Misc
    "Rope": "Ned's_Handmade_Rope",
    "Silk": "Silk_Trader_(shop)",
    "Spice": "Ardougne_Spice_Stall",
    "Chronicle": "Diango's_Toy_Store",
    "Empty pot": "Lumbridge_General_Store",
    "Empty jug": "Lumbridge_General_Store",
    "Empty bucket": "Lumbridge_General_Store",
}

# ---------------------------------------------------------------------------
# ANSI colors
# ---------------------------------------------------------------------------

RED = "\033[91m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
BOLD = "\033[1m"
DIM = "\033[90m"
RESET = "\033[0m"
SEPARATOR = DIM + "=" * 72 + RESET

# ---------------------------------------------------------------------------
# Embedded HTML dashboard
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DMM Scanner Dashboard</title>
<style>
  /* CSS Variables for theming */
  :root {
    --bg-primary: #0d1117;
    --bg-secondary: #161b22;
    --bg-tertiary: #21262d;
    --border-primary: #30363d;
    --border-secondary: #21262d;
    --text-primary: #e6edf3;
    --text-secondary: #8b949e;
    --text-muted: #484f58;
    --accent-blue: #58a6ff;
    --accent-green: #3fb950;
    --accent-red: #f85149;
    --accent-yellow: #d29922;
    --accent-gold: #ffa657;
    --hover-overlay: rgba(88, 166, 255, 0.06);
    --row-red-bg: rgba(248, 81, 73, 0.1);
    --row-yellow-bg: rgba(210, 153, 34, 0.1);
    --icon-shadow: rgba(0,0,0,0.5);
  }

  [data-theme="light"] {
    --bg-primary: #ffffff;
    --bg-secondary: #f6f8fa;
    --bg-tertiary: #eaeef2;
    --border-primary: #d0d7de;
    --border-secondary: #eaeef2;
    --text-primary: #1f2328;
    --text-secondary: #656d76;
    --text-muted: #8c959f;
    --accent-blue: #0969da;
    --accent-green: #1a7f37;
    --accent-red: #cf222e;
    --accent-yellow: #9a6700;
    --accent-gold: #bf8700;
    --hover-overlay: rgba(9, 105, 218, 0.06);
    --row-red-bg: rgba(207, 34, 46, 0.08);
    --row-yellow-bg: rgba(154, 103, 0, 0.08);
    --icon-shadow: rgba(0,0,0,0.2);
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: var(--bg-primary); color: var(--text-primary);
    font-family: "Cascadia Code", "Fira Code", "Consolas", monospace;
    font-size: 14px;
    transition: background 0.2s, color 0.2s;
  }
  .header {
    background: var(--bg-secondary); border-bottom: 1px solid var(--border-primary);
    padding: 16px 24px; display: flex; align-items: center; gap: 12px;
  }
  .header h1 { font-size: 18px; font-weight: 600; flex: 1; }
  .header-btn {
    background: var(--bg-tertiary); border: 1px solid var(--border-primary); color: var(--text-primary);
    padding: 8px 16px; border-radius: 6px; cursor: pointer;
    font-family: inherit; font-size: 13px; font-weight: 500;
    transition: background 0.15s, border-color 0.15s;
  }
  .header-btn:hover { background: var(--border-primary); border-color: var(--text-muted); }
  .header-btn.paused { background: #238636; border-color: #2ea043; color: #fff; }
  .header-btn.paused:hover { background: #2ea043; }
  .theme-btn { padding: 8px 12px; font-size: 16px; }
  .dot {
    width: 10px; height: 10px; border-radius: 50%;
    background: var(--accent-red); display: inline-block; flex-shrink: 0;
  }
  .dot.ok { background: var(--accent-green); }
  .status-bar {
    background: var(--bg-secondary); border-bottom: 1px solid var(--border-primary);
    padding: 10px 24px; display: flex; gap: 24px;
    color: var(--text-secondary); font-size: 13px;
  }
  .status-bar span { white-space: nowrap; }

  /* Tabs */
  .tabs {
    display: flex; background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-primary); padding: 0 24px;
  }
  .tab {
    background: none; border: none; color: var(--text-secondary);
    font-family: inherit; font-size: 14px;
    padding: 12px 20px; cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: color 0.15s, border-color 0.15s;
  }
  .tab:hover { color: var(--text-primary); }
  .tab.active { color: var(--text-primary); border-bottom-color: var(--accent-blue); font-weight: 600; }
  .tab-content { display: none; }
  .tab-content.active { display: block; }

  /* Stat cards */
  .cards { display: flex; gap: 16px; padding: 16px 24px; flex-wrap: wrap; }
  .card {
    background: var(--bg-secondary); border: 1px solid var(--border-primary);
    border-radius: 8px; padding: 16px 20px; flex: 1; min-width: 180px;
  }
  .card-label {
    color: var(--text-secondary); font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.5px; margin-bottom: 6px;
  }
  .card-value { font-size: 22px; font-weight: 700; }
  .gold { color: var(--accent-gold); }
  .green { color: var(--accent-green); }
  .red { color: var(--accent-red); }
  .blue { color: var(--accent-blue); }

  /* Table */
  .table-wrap { padding: 0 24px 24px; overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; min-width: 700px; }
  th {
    background: var(--bg-tertiary); position: sticky; top: 0; z-index: 1;
    text-align: left; padding: 10px 12px; font-weight: 600;
    color: var(--text-secondary); font-size: 11px; text-transform: uppercase;
    letter-spacing: 0.5px; border-bottom: 1px solid var(--border-primary);
    cursor: pointer; user-select: none;
  }
  th:hover { color: var(--text-primary); }
  th .sort-arrow { font-size: 10px; margin-left: 4px; }
  td {
    padding: 10px 12px; border-bottom: 1px solid var(--border-secondary);
    white-space: nowrap;
  }
  tbody tr { transition: background 0.1s; }
  tbody tr:hover { background: var(--hover-overlay) !important; }

  tr.row-red {
    background: var(--row-red-bg);
    border-left: 3px solid var(--accent-red);
  }
  tr.row-red td:first-child { padding-left: 9px; }
  tr.row-yellow {
    background: var(--row-yellow-bg);
    border-left: 3px solid var(--accent-yellow);
  }
  tr.row-yellow td:first-child { padding-left: 9px; }
  .price { color: var(--accent-gold); font-weight: 600; }
  .ratio { color: var(--accent-red); }
  .vol-high { color: var(--accent-green); font-weight: 600; }
  .vol-mid { color: var(--accent-yellow); }
  .vol-low { color: var(--text-secondary); }

  /* Item icons */
  .item-icon {
    width: 24px; height: 24px; vertical-align: middle;
    margin-right: 6px; image-rendering: pixelated;
    filter: drop-shadow(1px 1px 1px var(--icon-shadow));
  }
  .item-cell { display: flex; align-items: center; gap: 4px; }

  /* Wiki links */
  .item-link {
    color: var(--text-primary); text-decoration: none;
  }
  .item-link:hover {
    color: var(--accent-blue); text-decoration: underline;
    text-decoration-style: dotted;
  }
  .item-link:visited { color: var(--text-primary); }

  /* Pattern badges */
  .badge {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 11px; font-weight: 600;
  }
  .badge-single { background: var(--bg-tertiary); color: var(--text-secondary); }
  .badge-repeat { background: var(--row-yellow-bg); color: var(--accent-yellow); }
  .badge-pattern { background: var(--row-red-bg); color: var(--accent-red); }
  .badge-alch { background: rgba(191, 135, 0, 0.15); color: var(--accent-gold); }
  .badge-flip { background: rgba(26, 127, 55, 0.15); color: var(--accent-green); }

  /* Section titles */
  .section-title {
    color: var(--text-secondary); font-size: 13px; font-weight: 600;
    text-transform: uppercase; letter-spacing: 0.5px;
    padding: 20px 24px 0; margin: 0;
    border-top: 1px solid var(--border-secondary);
  }
  .section-title:first-of-type { border-top: none; }

  /* Favorites */
  .fav-btn {
    background: none; border: none; cursor: pointer;
    font-size: 16px; padding: 0 4px; color: var(--text-muted);
    transition: color 0.15s;
  }
  .fav-btn:hover { color: var(--accent-gold); }
  .fav-btn.favorited { color: var(--accent-gold); }
  tr.row-fav {
    background: rgba(255, 166, 87, 0.08);
    border-left: 3px solid var(--accent-gold);
  }
  tr.row-fav td:first-child { padding-left: 9px; }

  /* Filter buttons */
  .filter-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
    padding: 8px 0;
  }
  .filter-label {
    color: var(--text-muted);
    font-size: 13px;
    margin-right: 4px;
  }
  .filter-btn {
    background: var(--card-bg);
    border: 1px solid var(--border);
    color: var(--text);
    padding: 6px 14px;
    border-radius: 6px;
    cursor: pointer;
    font-size: 13px;
    transition: all 0.15s;
  }
  .filter-btn:hover {
    border-color: var(--accent-gold);
  }
  .filter-btn.active {
    background: var(--accent-gold);
    color: #1a1a2e;
    border-color: var(--accent-gold);
    font-weight: 600;
  }

  .empty {
    text-align: center; padding: 48px 24px; color: var(--text-muted); font-size: 15px;
  }
  .empty .spinner {
    display: inline-block; width: 18px; height: 18px;
    border: 2px solid var(--border-primary); border-top-color: var(--accent-blue);
    border-radius: 50%; animation: spin 1s linear infinite;
    vertical-align: middle; margin-right: 8px;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
</style>
</head>
<body>

<div class="header">
  <span class="dot" id="dot"></span>
  <h1>OSRS Deadman Mode &mdash; Scanner Dashboard</h1>
  <button class="header-btn theme-btn" id="theme-btn" onclick="toggleTheme()" title="Toggle light/dark mode">&#9790;</button>
  <button class="header-btn" id="pause-btn" onclick="togglePause()">Pause</button>
</div>
<div class="status-bar">
  <span id="poll-status">Connecting...</span>
  <span id="uptime">Uptime: --</span>
</div>

<!-- Tabs -->
<div class="tabs">
  <button class="tab active" data-tab="wash">Wash Trades</button>
  <button class="tab" data-tab="money">Money Making</button>
  <button class="tab" data-tab="arb">Arbitrage</button>
</div>

<!-- Wash Trades Tab -->
<div class="tab-content active" id="wash-tab">
  <div class="cards">
    <div class="card">
      <div class="card-label">Total Alerts</div>
      <div class="card-value red" id="wc-total">0</div>
    </div>
    <div class="card">
      <div class="card-label">Highest Ratio</div>
      <div class="card-value gold" id="wc-ratio">--</div>
    </div>
    <div class="card">
      <div class="card-label">Last Detection</div>
      <div class="card-value blue" id="wc-last">--</div>
    </div>
    <div class="card">
      <div class="card-label">Repeat Items</div>
      <div class="card-value gold" id="wc-repeats">0</div>
    </div>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th style="width:40px"></th>
        <th data-col="1" data-type="str">Detected</th>
        <th data-col="2" data-type="str">Item</th>
        <th data-col="3" data-type="num">Trade Price</th>
        <th data-col="4" data-type="num">Alch Value</th>
        <th data-col="5" data-type="num">Ratio</th>
        <th data-col="6" data-type="num">Volume</th>
        <th data-col="7" data-type="num">Last Trade</th>
        <th data-col="8" data-type="num">Pattern</th>
      </tr></thead>
      <tbody id="wash-tbody"></tbody>
    </table>
    <div class="empty" id="wash-empty">
      <span class="spinner"></span> Waiting for scanner data...
    </div>
  </div>
</div>

<!-- Money Making Tab -->
<div class="tab-content" id="money-tab">
  <div class="cards">
    <div class="card">
      <div class="card-label">Top Opportunity</div>
      <div class="card-value green" id="mc-top">--</div>
    </div>
    <div class="card">
      <div class="card-label">Total Daily GP</div>
      <div class="card-value gold" id="mc-gp">--</div>
    </div>
    <div class="card">
      <div class="card-label">Items Found</div>
      <div class="card-value blue" id="mc-count">0</div>
    </div>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th style="width:40px"></th>
        <th data-col="1" data-type="str">Item</th>
        <th data-col="2" data-type="num">NPC Price</th>
        <th data-col="3" data-type="num">GE Price</th>
        <th data-col="4" data-type="num">Markup</th>
        <th data-col="5" data-type="num">Daily Volume</th>
        <th data-col="6" data-type="num">Profit/Item</th>
        <th data-col="7" data-type="num">Total Daily GP</th>
        <th data-col="8" data-type="num">Last Sold</th>
        <th data-col="9" data-type="num">Heat</th>
      </tr></thead>
      <tbody id="money-tbody"></tbody>
    </table>
    <div class="empty" id="money-empty">
      <span class="spinner"></span> Scanning for opportunities...
    </div>
  </div>
</div>

<!-- Arbitrage Tab -->
<div class="tab-content" id="arb-tab">
  <!-- High Alch Section -->
  <h2 class="section-title">High Alch Arbitrage</h2>
  <div class="cards">
    <div class="card">
      <div class="card-label">Best Profit/Item</div>
      <div class="card-value gold" id="ac-alch">--</div>
    </div>
    <div class="card">
      <div class="card-label">Best Total Profit</div>
      <div class="card-value green" id="ac-alch-total">--</div>
    </div>
    <div class="card">
      <div class="card-label">Alch Opportunities</div>
      <div class="card-value blue" id="ac-alch-count">0</div>
    </div>
  </div>
  <div class="filter-bar">
    <span class="filter-label">Filter:</span>
    <button class="filter-btn active" data-filter="all">All Items</button>
    <button class="filter-btn" data-filter="stackable">Stackable Only</button>
    <button class="filter-btn" data-filter="liquid">High Liquidity</button>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th style="width:40px"></th>
        <th data-col="1" data-type="str">Item</th>
        <th data-col="2" data-type="num">Buy Price</th>
        <th data-col="3" data-type="num">Alch Value</th>
        <th data-col="4" data-type="num">Profit/Item</th>
        <th data-col="5" data-type="num">Volume</th>
        <th data-col="6" data-type="num">Total Profit</th>
        <th data-col="7" data-type="num">Last Traded</th>
      </tr></thead>
      <tbody id="alch-tbody"></tbody>
    </table>
    <div class="empty" id="alch-empty">
      <span class="spinner"></span> Scanning for alch opportunities...
    </div>
  </div>

  <!-- Flip Section -->
  <h2 class="section-title">Bid-Ask Spread Flipping</h2>
  <div class="cards">
    <div class="card">
      <div class="card-label">Best Margin</div>
      <div class="card-value gold" id="ac-spread">--</div>
    </div>
    <div class="card">
      <div class="card-label">Best Flip Score</div>
      <div class="card-value green" id="ac-score">--</div>
    </div>
    <div class="card">
      <div class="card-label">Flip Opportunities</div>
      <div class="card-value blue" id="ac-flip-count">0</div>
    </div>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr>
        <th style="width:40px"></th>
        <th data-col="1" data-type="str">Item</th>
        <th data-col="2" data-type="num">Buy Price</th>
        <th data-col="3" data-type="num">Sell Price</th>
        <th data-col="4" data-type="num">Margin</th>
        <th data-col="5" data-type="num">Volume</th>
        <th data-col="6" data-type="num">Flip Score</th>
        <th data-col="7" data-type="num">Last Sold</th>
      </tr></thead>
      <tbody id="flip-tbody"></tbody>
    </table>
    <div class="empty" id="flip-empty">
      <span class="spinner"></span> Scanning for flip opportunities...
    </div>
  </div>
</div>

<script>
const dot = document.getElementById('dot');
const pollEl = document.getElementById('poll-status');
const uptimeEl = document.getElementById('uptime');
const themeBtn = document.getElementById('theme-btn');

let lastPollTime = null;
let startTime = null;

// --- Theme Toggle ---

function setTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme);
  localStorage.setItem('dmm-scanner-theme', theme);
  themeBtn.innerHTML = theme === 'light' ? '&#9728;' : '&#9790;';
  themeBtn.title = theme === 'light' ? 'Switch to dark mode' : 'Switch to light mode';
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  setTheme(current === 'light' ? 'dark' : 'light');
}

// Load saved theme or default to dark
const savedTheme = localStorage.getItem('dmm-scanner-theme') || 'dark';
setTheme(savedTheme);

// --- Favorites ---

let favorites = JSON.parse(localStorage.getItem('dmm-scanner-favorites')) || [];
let lastData = null;

function isFavorite(itemId) {
  return favorites.includes(itemId);
}

function toggleFavorite(itemId) {
  const idx = favorites.indexOf(itemId);
  if (idx === -1) {
    favorites.push(itemId);
  } else {
    favorites.splice(idx, 1);
  }
  localStorage.setItem('dmm-scanner-favorites', JSON.stringify(favorites));
  // Re-render to update star icons
  if (lastData) {
    renderWash(lastData);
    renderMoney(lastData);
    renderArbitrage(lastData);
  }
}

function favCell(itemId) {
  const filled = isFavorite(itemId);
  const star = filled ? '&#9733;' : '&#9734;';
  const cls = filled ? 'fav-btn favorited' : 'fav-btn';
  return '<td><button class="' + cls + '" onclick="toggleFavorite(' + itemId + ')">' + star + '</button></td>';
}

// --- Stackable Item Detection ---
function isStackable(name) {
  const n = name.toLowerCase();

  // Stackable patterns (arrows, bolts, ores, etc.)
  const stackablePatterns = [
    /arrow/, /bolt(?!.*crossbow)/, /dart/, /throwing/, /javelin/,
    /\bore\b/, /\bbar\b/, /\blogs\b/, /seed/, /bone/,
    /feather/, /tips?$/, /scale/, /hide/, /leather/,
    /grimy/, /essence/, /shard/, /coin/, /token/,
    /\brune\b(?!.*(?:axe|sword|scim|dagger|mace|helm|plate|chain|legs|kite|sq|full|med|boots|gloves|crossbow|pickaxe|hatchet|cane|spear|hasta|claws))/
  ];

  // Gems (stackable when uncut/cut, not jewelry)
  const gems = ['sapphire', 'emerald', 'ruby', 'diamond', 'dragonstone', 'onyx', 'zenyte', 'jade', 'opal', 'topaz'];
  if (gems.some(g => n.includes(g) && !n.includes('ring') && !n.includes('necklace') && !n.includes('amulet') && !n.includes('bracelet'))) {
    return true;
  }

  return stackablePatterns.some(p => p.test(n));
}

// --- Alch Filter State ---
let alchFilter = 'all';  // 'all', 'stackable', 'liquid'

document.querySelectorAll('.filter-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    alchFilter = btn.dataset.filter;
    if (lastData) renderArbitrage(lastData);
  });
});

// --- Helpers ---

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

function fmtGp(n) {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M gp';
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K gp';
  return n.toLocaleString() + ' gp';
}

function fmtGpFull(n) {
  return n.toLocaleString() + ' gp';
}

function fmtTime(iso) {
  return new Date(iso).toLocaleTimeString();
}

function fmtUptime(startIso) {
  if (!startIso) return '--';
  const s = Math.floor((Date.now() - new Date(startIso).getTime()) / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return h + 'h ' + m + 'm';
  if (m > 0) return m + 'm ' + sec + 's';
  return sec + 's';
}

function nameCell(name, innerOnly) {
  const slug = encodeURIComponent(name).replace(/%20/g, '_');
  const url = 'https://oldschool.runescape.wiki/w/' + slug;
  const imgUrl = 'https://oldschool.runescape.wiki/images/' + slug + '.png';
  const img = '<img class="item-icon" src="' + imgUrl + '" alt="" loading="lazy" onerror="this.style.display=&quot;none&quot;">';
  const inner = '<span class="item-cell">' + img + '<a class="item-link" href="' + url + '" target="_blank">' + esc(name) + '</a></span>';
  if (innerOnly) return inner;
  return '<td>' + inner + '</td>';
}

function shopCell(npcValue, shopUrl, innerOnly) {
  if (shopUrl) {
    const url = 'https://oldschool.runescape.wiki/w/' + encodeURIComponent(shopUrl).replace(/%20/g, '_');
    const link = '<a class="item-link" href="' + url + '" target="_blank">' + fmtGpFull(npcValue) + '</a>';
    if (innerOnly) return link;
    return '<td>' + link + '</td>';
  }
  if (innerOnly) return fmtGpFull(npcValue);
  return '<td>' + fmtGpFull(npcValue) + '</td>';
}

function fmtTradeTime(unixTs) {
  if (!unixTs) return '--';
  const d = new Date(unixTs * 1000);
  const now = Date.now();
  const ago = Math.floor((now - d.getTime()) / 60000);
  if (ago < 1) return 'just now';
  if (ago < 60) return ago + 'm ago';
  if (ago < 1440) return Math.floor(ago / 60) + 'h ago';
  return d.toLocaleDateString();
}

function heatBadge(heat) {
  if (!heat || heat <= 0) return '<span class="badge badge-single">--</span>';
  let cls = 'badge-single';
  if (heat >= 100000) cls = 'badge-pattern';
  else if (heat >= 30000) cls = 'badge-repeat';
  return '<span class="badge ' + cls + '">' + fmtGp(heat) + '</span>';
}

function patternBadge(sightings) {
  if (!sightings || sightings <= 1) return '<span class="badge badge-single">1x</span>';
  if (sightings <= 3) return '<span class="badge badge-repeat">' + sightings + 'x</span>';
  return '<span class="badge badge-pattern">' + sightings + 'x &#9888;</span>';
}

// --- Tabs ---

document.querySelectorAll('.tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(x => x.classList.remove('active'));
    t.classList.add('active');
    document.getElementById(t.dataset.tab + '-tab').classList.add('active');
  });
});

// --- Status ticker (runs every second) ---

function tickStatus() {
  if (lastPollTime) {
    const ago = Math.floor((Date.now() - new Date(lastPollTime).getTime()) / 1000);
    dot.className = ago < 30 ? 'dot ok' : 'dot';
    pollEl.textContent = 'Last poll: ' + ago + 's ago';
  }
  uptimeEl.textContent = 'Uptime: ' + fmtUptime(startTime);
}
setInterval(tickStatus, 1000);

// --- Render ---

function renderWash(data) {
  const alerts = data.alerts || [];
  const tbody = document.getElementById('wash-tbody');
  const empty = document.getElementById('wash-empty');

  // Cards
  document.getElementById('wc-total').textContent = data.total_alerts;
  document.getElementById('wc-repeats').textContent = data.repeat_items || 0;
  if (alerts.length > 0) {
    const maxR = Math.max(...alerts.map(a => a.ratio));
    document.getElementById('wc-ratio').textContent = maxR.toLocaleString() + 'x';
    document.getElementById('wc-last').textContent = fmtTime(alerts[alerts.length - 1].time);
  }

  if (alerts.length === 0) {
    empty.style.display = 'block';
    tbody.innerHTML = '';
    return;
  }
  empty.style.display = 'none';

  let html = '';
  for (let i = alerts.length - 1; i >= 0; i--) {
    const a = alerts[i];
    const fav = isFavorite(a.item_id);
    let cls = a.tier === 'red' ? 'row-red' : 'row-yellow';
    if (fav) cls += ' row-fav';
    html += '<tr class="' + cls + '" data-item-id="' + a.item_id + '">'
      + favCell(a.item_id)
      + '<td data-val="' + a.time + '">' + esc(fmtTime(a.time)) + '</td>'
      + '<td data-val="' + esc(a.name) + '">' + nameCell(a.name, true) + '</td>'
      + '<td data-val="' + a.price + '" class="price">' + fmtGpFull(a.price) + '</td>'
      + '<td data-val="' + a.highalch + '">' + fmtGpFull(a.highalch) + '</td>'
      + '<td data-val="' + a.ratio + '" class="ratio">' + Number(a.ratio).toLocaleString() + 'x</td>'
      + '<td data-val="' + a.volume + '">' + a.volume + '</td>'
      + '<td data-val="' + (a.high_time || 0) + '">' + fmtTradeTime(a.high_time) + '</td>'
      + '<td data-val="' + (a.sightings || 1) + '">' + patternBadge(a.sightings) + '</td>'
      + '</tr>';
  }
  tbody.innerHTML = html;
  reapplySort('wash-tbody');
}

function renderMoney(data) {
  const opps = data.opportunities || [];
  const tbody = document.getElementById('money-tbody');
  const empty = document.getElementById('money-empty');

  // Cards
  document.getElementById('mc-count').textContent = opps.length;
  if (opps.length > 0) {
    document.getElementById('mc-top').textContent = opps[0].name;
    const totalGp = opps.reduce((s, o) => s + o.total_gp, 0);
    document.getElementById('mc-gp').textContent = fmtGp(totalGp);
  }

  if (opps.length === 0) {
    empty.style.display = 'block';
    tbody.innerHTML = '';
    return;
  }
  empty.style.display = 'none';

  let html = '';
  for (const o of opps) {
    let vc = 'vol-low';
    if (o.volume >= 1000) vc = 'vol-high';
    else if (o.volume >= 100) vc = 'vol-mid';
    const fav = isFavorite(o.item_id);
    const rowCls = fav ? 'row-fav' : '';

    html += '<tr class="' + rowCls + '" data-item-id="' + o.item_id + '">'
      + favCell(o.item_id)
      + '<td data-val="' + esc(o.name) + '">' + nameCell(o.name, true) + '</td>'
      + '<td data-val="' + o.npc_value + '">' + shopCell(o.npc_value, o.shop_url, true) + '</td>'
      + '<td data-val="' + o.ge_price + '" class="price">' + fmtGpFull(o.ge_price) + '</td>'
      + '<td data-val="' + o.markup + '" class="ratio">' + o.markup.toLocaleString() + 'x</td>'
      + '<td data-val="' + o.volume + '" class="' + vc + '">' + o.volume.toLocaleString() + '</td>'
      + '<td data-val="' + o.profit_per + '" class="price">' + fmtGp(o.profit_per) + '</td>'
      + '<td data-val="' + o.total_gp + '" class="price">' + fmtGp(o.total_gp) + '</td>'
      + '<td data-val="' + (o.high_time || 0) + '">' + fmtTradeTime(o.high_time) + '</td>'
      + '<td data-val="' + (o.heat || 0) + '">' + heatBadge(o.heat) + '</td>'
      + '</tr>';
  }
  tbody.innerHTML = html;
  reapplySort('money-tbody');
}

function renderArbitrage(data) {
  const alchOpps = data.alch_opps || [];
  const spreadOpps = data.spread_opps || [];

  // --- High Alch Section ---
  const alchTbody = document.getElementById('alch-tbody');
  const alchEmpty = document.getElementById('alch-empty');

  // Apply filter to alch opportunities
  let filteredAlch = alchOpps;
  if (alchFilter === 'stackable') {
    filteredAlch = alchOpps.filter(a => isStackable(a.name));
  } else if (alchFilter === 'liquid') {
    filteredAlch = alchOpps.filter(a => a.volume >= 500);
  }

  // Alch Cards (show filtered stats)
  document.getElementById('ac-alch-count').textContent = filteredAlch.length;
  if (filteredAlch.length > 0) {
    document.getElementById('ac-alch').textContent = fmtGp(filteredAlch[0].profit) + '/ea';
    document.getElementById('ac-alch-total').textContent = fmtGp(filteredAlch[0].total_profit);
  } else {
    document.getElementById('ac-alch').textContent = '--';
    document.getElementById('ac-alch-total').textContent = '--';
  }

  if (filteredAlch.length === 0) {
    alchEmpty.style.display = 'block';
    alchEmpty.innerHTML = alchOpps.length > 0
      ? '<span>No items match the current filter</span>'
      : '<span class="spinner"></span> Scanning for alch opportunities...';
    alchTbody.innerHTML = '';
  } else {
    alchEmpty.style.display = 'none';
    let alchHtml = '';
    for (const a of filteredAlch) {
      let vc = 'vol-low';
      if (a.volume >= 1000) vc = 'vol-high';
      else if (a.volume >= 100) vc = 'vol-mid';
      const fav = isFavorite(a.item_id);
      const rowCls = fav ? 'row-fav' : '';

      alchHtml += '<tr class="' + rowCls + '" data-item-id="' + a.item_id + '">'
        + favCell(a.item_id)
        + '<td data-val="' + esc(a.name) + '">' + nameCell(a.name, true) + '</td>'
        + '<td data-val="' + a.buy_price + '" class="price">' + fmtGpFull(a.buy_price) + '</td>'
        + '<td data-val="' + a.alch_value + '" class="gold">' + fmtGpFull(a.alch_value) + '</td>'
        + '<td data-val="' + a.profit + '" class="green">' + fmtGp(a.profit) + '</td>'
        + '<td data-val="' + a.volume + '" class="' + vc + '">' + a.volume.toLocaleString() + '</td>'
        + '<td data-val="' + a.total_profit + '" class="gold">' + fmtGp(a.total_profit) + '</td>'
        + '<td data-val="' + (a.low_time||0) + '">' + fmtTradeTime(a.low_time) + '</td>'
        + '</tr>';
    }
    alchTbody.innerHTML = alchHtml;
    reapplySort('alch-tbody');
  }

  // --- Flip Section ---
  const flipTbody = document.getElementById('flip-tbody');
  const flipEmpty = document.getElementById('flip-empty');

  // Flip Cards
  document.getElementById('ac-flip-count').textContent = spreadOpps.length;
  if (spreadOpps.length > 0) {
    document.getElementById('ac-spread').textContent = spreadOpps[0].spread_pct + '%';
    document.getElementById('ac-score').textContent = fmtGp(spreadOpps[0].flip_score);
  }

  if (spreadOpps.length === 0) {
    flipEmpty.style.display = 'block';
    flipTbody.innerHTML = '';
  } else {
    flipEmpty.style.display = 'none';
    let flipHtml = '';
    for (const s of spreadOpps) {
      let vc = 'vol-low';
      if (s.volume >= 1000) vc = 'vol-high';
      else if (s.volume >= 100) vc = 'vol-mid';
      const fav = isFavorite(s.item_id);
      const rowCls = fav ? 'row-fav' : '';

      flipHtml += '<tr class="' + rowCls + '" data-item-id="' + s.item_id + '">'
        + favCell(s.item_id)
        + '<td data-val="' + esc(s.name) + '">' + nameCell(s.name, true) + '</td>'
        + '<td data-val="' + s.buy_price + '" class="price">' + fmtGpFull(s.buy_price) + '</td>'
        + '<td data-val="' + s.sell_price + '" class="price">' + fmtGpFull(s.sell_price) + '</td>'
        + '<td data-val="' + s.spread_pct + '" class="green">' + s.spread_pct + '%</td>'
        + '<td data-val="' + s.volume + '" class="' + vc + '">' + s.volume.toLocaleString() + '</td>'
        + '<td data-val="' + s.flip_score + '" class="gold">' + fmtGp(s.flip_score) + '</td>'
        + '<td data-val="' + (s.high_time||0) + '">' + fmtTradeTime(s.high_time) + '</td>'
        + '</tr>';
    }
    flipTbody.innerHTML = flipHtml;
    reapplySort('flip-tbody');
  }
}

// --- Column sorting ---

let sortState = {};  // { tbodyId: { col, dir } }

function sortTable(th) {
  const table = th.closest('table');
  const tbody = table.querySelector('tbody');
  const col = parseInt(th.dataset.col);
  const type = th.dataset.type || 'str';
  const tbodyId = tbody.id;

  // Toggle direction
  const prev = sortState[tbodyId];
  let dir = 'desc';
  if (prev && prev.col === col && prev.dir === 'desc') dir = 'asc';
  sortState[tbodyId] = { col, dir };

  // Update arrow indicators
  table.querySelectorAll('th .sort-arrow').forEach(a => a.remove());
  const arrow = dir === 'asc' ? '\\u25B2' : '\\u25BC';
  th.insertAdjacentHTML('beforeend', '<span class="sort-arrow">' + arrow + '</span>');

  // Sort rows
  const rows = Array.from(tbody.querySelectorAll('tr'));
  rows.sort((a, b) => {
    let va = a.children[col].dataset.val || a.children[col].textContent;
    let vb = b.children[col].dataset.val || b.children[col].textContent;
    if (type === 'num') {
      va = parseFloat(va) || 0;
      vb = parseFloat(vb) || 0;
    }
    if (va < vb) return dir === 'asc' ? -1 : 1;
    if (va > vb) return dir === 'asc' ? 1 : -1;
    return 0;
  });

  rows.forEach(r => tbody.appendChild(r));
}

function reapplySort(tbodyId) {
  const s = sortState[tbodyId];
  if (!s) return;
  const table = document.getElementById(tbodyId).closest('table');
  const th = table.querySelector('th[data-col="' + s.col + '"]');
  if (!th) return;
  // Force same direction by flipping first (sortTable toggles)
  sortState[tbodyId] = { col: s.col, dir: s.dir === 'asc' ? 'desc' : 'asc' };
  sortTable(th);
}

document.querySelectorAll('th[data-col]').forEach(th => {
  th.addEventListener('click', () => sortTable(th));
});

// Default sort: money by Heat, alch by total profit, flip by flip score
// (column indices shifted +1 due to new Fav column)
sortState['money-tbody'] = { col: 9, dir: 'desc' };  // Heat
sortState['alch-tbody'] = { col: 6, dir: 'desc' };   // Total Profit
sortState['flip-tbody'] = { col: 6, dir: 'desc' };   // Flip Score

// --- Pause/Resume ---

let isPaused = false;
const pauseBtn = document.getElementById('pause-btn');

async function togglePause() {
  const endpoint = isPaused ? '/api/resume' : '/api/pause';
  try {
    await fetch(endpoint, { method: 'POST' });
    isPaused = !isPaused;
    pauseBtn.textContent = isPaused ? 'Resume' : 'Pause';
    pauseBtn.className = isPaused ? 'header-btn paused' : 'header-btn';
  } catch (e) {
    console.error('Failed to toggle pause:', e);
  }
}

// --- Polling ---

let lastDataHash = '';

function hashData(data) {
  // Simple hash: poll_count + alert count + opp count + arb counts
  const arbCount = (data.alch_opps || []).length + (data.spread_opps || []).length;
  return data.poll_count + '-' + data.total_alerts + '-' + data.total_opportunities + '-' + arbCount;
}

async function poll() {
  try {
    const r = await fetch('/api/alerts');
    const data = await r.json();
    lastPollTime = data.last_poll;
    startTime = data.start_time;
    lastData = data;  // Store for favorites re-render

    // Sync pause state from server
    if (data.paused !== isPaused) {
      isPaused = data.paused;
      pauseBtn.textContent = isPaused ? 'Resume' : 'Pause';
      pauseBtn.className = isPaused ? 'header-btn paused' : 'header-btn';
    }

    tickStatus();

    // Only re-render if data actually changed
    const newHash = hashData(data);
    if (newHash !== lastDataHash) {
      lastDataHash = newHash;
      renderWash(data);
      renderMoney(data);
      renderArbitrage(data);
    }
  } catch (e) {
    dot.className = 'dot';
    pollEl.textContent = 'Connection lost';
  }
}

poll();
setInterval(poll, 10000);  // Poll every 10s (was 5s)
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def fetch_json(endpoint):
    """Fetch JSON from the OSRS Wiki prices API. Returns None on error."""
    url = BASE_URL + endpoint
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"{DIM}[warn] API error on {endpoint}: {exc}{RESET}", file=sys.stderr)
        return None


def load_mapping():
    """Load item mapping. Returns {item_id: {name, highalch, ...}}."""
    data = fetch_json("/mapping")
    if not data:
        return {}
    return {item["id"]: item for item in data}


def load_volumes():
    """Load 24h volumes. Returns {item_id: total_volume}."""
    raw = fetch_json("/24h")
    if not raw:
        return {}
    volumes = {}
    for item_id_str, entry in raw.get("data", {}).items():
        high_vol = entry.get("highPriceVolume") or 0
        low_vol = entry.get("lowPriceVolume") or 0
        volumes[int(item_id_str)] = high_vol + low_vol
    return volumes


# ---------------------------------------------------------------------------
# Thread-safe alert store
# ---------------------------------------------------------------------------

class AlertStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._alerts = []
        self._seen = {}  # {dedup_key: timestamp} — time-windowed dedup
        self._opportunities = []
        self._last_poll = None
        self.start_time = datetime.now()
        self._poll_count = 0
        self._item_history = {}  # {item_id: [{"price", "time", "high_time"}, ...]}
        self._paused = False
        self._alch_opps = []     # high alch arbitrage opportunities
        self._spread_opps = []   # bid-ask spread opportunities

    def add_alert(self, alert_dict, dedup_key):
        """Time-windowed dedup: same (item_id, price) within DEDUP_WINDOW = skip."""
        with self._lock:
            now = time.time()
            if dedup_key in self._seen:
                if now - self._seen[dedup_key] < DEDUP_WINDOW:
                    return False
            self._seen[dedup_key] = now

            # Record in per-item history
            item_id = alert_dict["item_id"]
            if item_id not in self._item_history:
                self._item_history[item_id] = []
            self._item_history[item_id].append({
                "price": alert_dict["price"],
                "time": alert_dict["time"],
                "high_time": alert_dict.get("high_time"),
            })

            # Enrich alert with pattern info
            history = self._item_history[item_id]
            alert_dict["sightings"] = len(history)
            alert_dict["first_seen"] = history[0]["time"]

            self._alerts.append(alert_dict)
            # Cap alerts to prevent unbounded memory growth
            if len(self._alerts) > MAX_ALERTS:
                self._alerts = self._alerts[-MAX_ALERTS:]
            return True

    def set_opportunities(self, opps_list):
        """Replace the full opportunity list (called each poll cycle)."""
        with self._lock:
            self._opportunities = opps_list

    def set_arbitrage(self, alch_list, spread_list):
        """Replace arbitrage opportunities (called each poll cycle)."""
        with self._lock:
            self._alch_opps = alch_list
            self._spread_opps = spread_list

    def record_poll(self):
        with self._lock:
            self._last_poll = datetime.now()
            self._poll_count += 1

    def is_paused(self):
        with self._lock:
            return self._paused

    def set_paused(self, paused):
        with self._lock:
            self._paused = paused

    def get_state(self):
        with self._lock:
            repeat_items = sum(
                1 for h in self._item_history.values() if len(h) >= 2
            )
            return {
                "alerts": list(self._alerts),
                "opportunities": list(self._opportunities),
                "alch_opps": list(self._alch_opps),
                "spread_opps": list(self._spread_opps),
                "last_poll": self._last_poll.isoformat() if self._last_poll else None,
                "start_time": self.start_time.isoformat(),
                "total_alerts": len(self._alerts),
                "total_opportunities": len(self._opportunities),
                "poll_count": self._poll_count,
                "repeat_items": repeat_items,
                "paused": self._paused,
            }


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def build_safe_list(mapping, volumes):
    """Filter mapping to low-volume items (volume < VOLUME_THRESHOLD)."""
    safe = {}
    for item_id, item in mapping.items():
        if volumes.get(item_id, 0) < VOLUME_THRESHOLD:
            safe[item_id] = item
    print(f"Built safe list: {len(safe)} items with < {VOLUME_THRESHOLD} daily volume")
    return safe


def check_latest(mapping, safe_list, volumes, store):
    """Fetch latest prices, run both scanners, record results."""
    raw = fetch_json("/latest")
    if not raw:
        return

    latest = raw.get("data", {})

    # --- Phase 1: Wash trade detection (safe_list only) ---

    for item_id, item in safe_list.items():
        entry = latest.get(str(item_id))
        if not entry:
            continue

        high_price = entry.get("high")
        if high_price is None:
            continue

        highalch = item.get("highalch") or 0
        ratio = high_price / (highalch + 1)

        if ratio <= RATIO_THRESHOLD:
            continue
        if high_price <= PRICE_THRESHOLD:
            continue

        vol = volumes.get(item_id, 0)
        if vol >= VOLUME_THRESHOLD:
            continue

        # Skip excluded items (legitimate rare gear)
        name = item.get("name", f"Item #{item_id}")
        if name in WASH_TRADE_EXCLUSIONS:
            continue

        # Deduplicate
        dedup_key = (item_id, high_price)
        high_time = entry.get("highTime")  # unix timestamp of actual trade
        alert = {
            "time": datetime.now().isoformat(),
            "item_id": item_id,
            "name": name,
            "price": high_price,
            "highalch": highalch,
            "ratio": round(ratio, 1),
            "volume": vol,
            "tier": "red" if high_price > HIGH_VALUE_THRESHOLD else "yellow",
            "high_time": high_time,
        }

        if not store.add_alert(alert, dedup_key):
            continue

        # Console output
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        msg = (
            f"[{ts}] SUSPICIOUS: {name} traded at {high_price:,}. "
            f"Alch: {highalch:,}. Ratio: {ratio:,.0f}x. Volume: {vol}"
        )
        if high_price > HIGH_VALUE_THRESHOLD:
            print(f"\n{SEPARATOR}")
            print(f"{RED}{BOLD}{msg}{RESET}")
            print(f"{SEPARATOR}\n")
        else:
            print(f"{YELLOW}{msg}{RESET}")

    # --- Phase 2: Money making opportunities (NPC shop allowlist) ---

    opportunities = []
    for item_id, item in mapping.items():
        name = item.get("name", "")
        if name not in NPC_SHOP_ITEMS:
            continue

        entry = latest.get(str(item_id))
        if not entry:
            continue

        ge_high = entry.get("high")
        if ge_high is None or ge_high <= 0:
            continue

        npc_value = item.get("value") or 0
        if npc_value <= 0:
            continue

        vol = volumes.get(item_id, 0)
        if vol < MM_MIN_VOLUME:
            continue

        markup = ge_high / npc_value
        if markup < MM_MARKUP_THRESHOLD:
            continue

        profit_per = ge_high - npc_value
        total_gp = profit_per * vol
        high_time = entry.get("highTime")  # unix timestamp of last sale

        # Heat score: total_gp weighted by recency
        now_ts = int(time.time())
        if high_time:
            age_hours = (now_ts - high_time) / 3600
            if age_hours < 1:
                recency = 1.0
            elif age_hours < 6:
                recency = 0.7
            elif age_hours < 24:
                recency = 0.4
            else:
                recency = 0.2
        else:
            recency = 0.1
        heat = int(total_gp * recency)

        opportunities.append({
            "item_id": item_id,
            "name": name,
            "npc_value": npc_value,
            "ge_price": ge_high,
            "markup": round(markup, 1),
            "volume": vol,
            "profit_per": profit_per,
            "total_gp": total_gp,
            "shop_url": NPC_SHOP_URLS.get(name, ""),
            "high_time": high_time,
            "heat": heat,
        })

    # Sort by heat score (profit × recency, best opportunities first)
    opportunities.sort(key=lambda x: x["heat"], reverse=True)
    store.set_opportunities(opportunities)

    # --- Phase 3: High Alch Arbitrage ---

    alch_opps = []
    for item_id, item in mapping.items():
        entry = latest.get(str(item_id))
        if not entry:
            continue

        ge_low = entry.get("low")
        if ge_low is None or ge_low <= 0:
            continue

        highalch = item.get("highalch") or 0
        if highalch <= 0:
            continue

        profit = highalch - ge_low - NATURE_RUNE_COST
        if profit < MIN_ALCH_PROFIT:
            continue

        vol = volumes.get(item_id, 0)
        if vol < 10:  # need some volume to be realistic
            continue

        name = item.get("name", f"Item #{item_id}")
        alch_opps.append({
            "item_id": item_id,
            "name": name,
            "buy_price": ge_low,
            "alch_value": highalch,
            "profit": profit,
            "volume": vol,
            "total_profit": profit * vol,
            "low_time": entry.get("lowTime"),
        })

    alch_opps.sort(key=lambda x: x["profit"], reverse=True)

    # --- Phase 4: Bid-Ask Spread Scanner ---

    spread_opps = []
    for item_id_str, entry in latest.items():
        item_id = int(item_id_str)
        item = mapping.get(item_id)
        if not item:
            continue

        ge_high = entry.get("high")
        ge_low = entry.get("low")
        if not ge_high or not ge_low or ge_low <= 0:
            continue

        spread = ge_high - ge_low
        spread_pct = (spread / ge_low) * 100
        if spread_pct < MIN_SPREAD_PCT:
            continue

        vol = volumes.get(item_id, 0)
        if vol < MIN_FLIP_VOLUME:
            continue

        name = item.get("name", f"Item #{item_id}")
        # Flip score: spread * volume = total daily profit potential
        flip_score = spread * vol
        spread_opps.append({
            "item_id": item_id,
            "name": name,
            "buy_price": ge_low,
            "sell_price": ge_high,
            "spread": spread,
            "spread_pct": round(spread_pct, 1),
            "volume": vol,
            "flip_score": flip_score,
            "high_time": entry.get("highTime"),
        })

    # Sort by flip score (spread × volume) — best combo of margin + liquidity
    spread_opps.sort(key=lambda x: x["flip_score"], reverse=True)
    store.set_arbitrage(alch_opps, spread_opps)

    # Console summary on first poll
    if store._poll_count == 0 and opportunities:
        top = opportunities[0]
        print(
            f"{GREEN}Money Making: {len(opportunities)} opportunities. "
            f"Top: {top['name']} ({top['markup']}x, "
            f"{top['total_gp']:,} gp/day){RESET}"
        )
    if store._poll_count == 0 and (alch_opps or spread_opps):
        print(
            f"{GREEN}Arbitrage: {len(alch_opps)} alch opps, "
            f"{len(spread_opps)} spread opps{RESET}"
        )

    store.record_poll()


def scanner_loop(mapping, safe_list, store):
    """Background thread: polls API and records alerts."""
    while True:
        if not store.is_paused():
            # Refresh 24h volumes each cycle for current liquidity data
            volumes = load_volumes() or {}
            check_latest(mapping, safe_list, volumes, store)
        time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Web server
# ---------------------------------------------------------------------------

class DashboardHandler(BaseHTTPRequestHandler):
    store = None

    def do_GET(self):
        if self.path == "/":
            body = DASHBOARD_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == "/api/alerts":
            data = json.dumps(self.store.get_state()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        else:
            self.send_error(404)

    def do_POST(self):
        if self.path == "/api/pause":
            self.store.set_paused(True)
            self._json_response({"paused": True})
        elif self.path == "/api/resume":
            self.store.set_paused(False)
            self._json_response({"paused": False})
        else:
            self.send_error(404)

    def _json_response(self, obj):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass  # suppress per-request logging


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"{CYAN}{BOLD}OSRS Deadman Mode — Scanner Dashboard{RESET}")
    print(f"{CYAN}{'=' * 40}{RESET}\n")

    print("Loading item mapping...")
    mapping = load_mapping()
    if not mapping:
        print("ERROR: Failed to load item mapping. Exiting.")
        return

    print(f"Loaded {len(mapping)} items.")

    print("Loading 24h volume data...")
    volumes = load_volumes()
    if not volumes:
        print("ERROR: Failed to load volume data. Exiting.")
        return

    safe_list = build_safe_list(mapping, volumes)
    if not safe_list:
        print("WARNING: No low-volume items found. Nothing to monitor.")
        return

    store = AlertStore()

    # Start scanner in background
    scanner_thread = threading.Thread(
        target=scanner_loop,
        args=(mapping, safe_list, store),
        daemon=True,
    )
    scanner_thread.start()
    print(f"Scanner polling every {POLL_INTERVAL}s (wash trades + money making).")

    # Start web server on main thread
    DashboardHandler.store = store
    server = ThreadingHTTPServer(("0.0.0.0", WEB_PORT), DashboardHandler)
    print(f"Dashboard: {CYAN}http://localhost:{WEB_PORT}{RESET}")
    print(f"Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        state = store.get_state()
        print(
            f"\n{CYAN}Scanner stopped. "
            f"{state['total_alerts']} wash trade alerts, "
            f"{state['total_opportunities']} money making items.{RESET}"
        )


if __name__ == "__main__":
    main()
