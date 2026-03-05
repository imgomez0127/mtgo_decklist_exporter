import asyncio
from collections.abc import Sequence
import dataclasses
from datetime import datetime
import itertools
import random
import re
import time

from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright
import requests

# Initialize FastMCP server
mcp = FastMCP('mtgo_decklist_exporter')

# Shared Headers
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}


@dataclasses.dataclass
class Decklist:
    """Data representation of a decklist

    Args:
      player: Name of the player who placed with the deck.
      mainboard: Cards in the main deck.
      sideboard: Cards in the sideboard.
    """
    player: str
    mainboard: Sequence[str]
    sideboard: Sequence[str]


async def get_events(
        date: datetime,
        mtg_format: str = None
) -> Sequence[str]:
    """
    Finds MTGO tournament URLs for a specific date (YYYY-MM-DD).
    Optionally filters by format (e.g., 'modern', 'legacy').

    Args:
      date: Date of the MTGO events.
      mtg_format: MTGO format of the event
    """
    archive_url = f'https://www.mtgo.com/decklists/{date.year}/{date.month}'

    response = requests.get(archive_url, headers=HEADERS)
    soup = BeautifulSoup(response.text, 'lxml')
    pattern = re.compile(rf'/decklist/(?P<type>.+)-{date.year}-{date.month:02d}-{date.day:02d}(?P<id>\d+)')
    events = set()
    for link in soup.find_all('a', href=True):
        match = pattern.search(link['href'])
        if match:
            event_type = match.group('type')
            if mtg_format is None or mtg_format.lower() in event_type.lower():
                full_url = "https://www.mtgo.com" + link['href']
                events.add(full_url)
    return events


async def get_event_decklists(event_url: str) -> Sequence[Decklist]:
    """
    Scrapes all decklists from a specific MTGO event URL.
    """
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=HEADERS['User-Agent'])
        page = await context.new_page()

        # Navigate and wait for JS to render
        await page.goto(event_url)
        try:
            # Wait for the main decklist container to load
            await page.wait_for_selector('section.decklist', timeout=15000)
            content = await page.content()
        except Exception as e:
            await browser.close()
            return []

        await browser.close()
    soup = BeautifulSoup(content, 'lxml')

    decks = []
    deck_containers = soup.find_all('section', class_='decklist')

    for container in deck_containers:
        player_list = container.find_all(class_='decklist-player')
        if player_list:
            player = player_list[0].get_text(strip=True)
            mainboard = []
            sideboard = []
            mainboard_container = container.find_all(
                class_='decklist-category-columns'
            )
            if mainboard_container:
                mainboard = [
                    card.string for card in
                    mainboard_container[0].find_all(class_='decklist-card-link')
                ]
            sideboard_container = container.find_all(
                class_='decklist-sideboard'
            )
            if sideboard_container:
                sideboard = [
                    card.string for card in
                    sideboard_container[0].find_all(class_='decklist-card-link')
                ]
            decks.append(Decklist(player, mainboard, sideboard))
    return decks


def format_decklist_output(deck_data):
    """
    Transforms a deck dictionary into a labeled readable format.
    Format:
    Player: Player Name
    Mainboard:
    4 Card Name

    Sideboard:
    1 Sideboard Card
    """
    lines = []

    # 1. Player Header
    lines.append(f'Player: {deck_data.player}')

    # 2. Mainboard Section
    lines.append('--Mainboard--')
    for card in deck_data.mainboard:
        lines.append(f'{card}')

    lines.append('\n--Sideboard--')
    for card in deck_data.sideboard:
        lines.append(f'{card}')
    return '\n'.join(lines)


@mcp.tool()
async def get_decklists(
        date: str,
        mtg_format: str | None = None,
        amount: int = 5
):
    """
    Gets all decklists for @target_date for a format or all events.

    Args:
      date: Date we are getting data for formatted as YYYY-MM-DD.
      mtg_format: The MTG format we are getting decklists for.
        If this is None, then we will grab all formats.
      amount: Number of decks to return in the output.

    Returns:
      A string with @amount of decklists that were for the @target_date
      filtered by format using @mtg_format.
    """
    try:
        date = datetime.strptime(date, '%Y-%m-%d')
    except ValueError:
        return 'The input date was not formatted as %Y-%m-%d'
    events = await get_events(date, mtg_format)
    decklists = []
    for event in events:
        event_decklists = await get_event_decklists(event)
        decklists.extend(event_decklists)
    sampled_decks = random.sample(
        decklists,
        k=min(amount, len(decklists))
    )
    return '\n\n'.join(
        format_decklist_output(decklist)
        for decklist in sampled_decks
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
