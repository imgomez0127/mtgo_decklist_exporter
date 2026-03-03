import asyncio
import itertools
import random
import re
import time

from bs4 import BeautifulSoup
from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright
import requests

# Initialize FastMCP server
mcp = FastMCP("mtgo_decklist_exporter")

# Shared Headers
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


async def get_events(target_date: str, format_filter: str = None) -> list:
    """
    Finds MTGO tournament URLs for a specific date (YYYY-MM-DD).
    Optionally filters by format (e.g., 'modern', 'legacy').
    """
    year, month, day = target_date.split('-')
    archive_url = f"https://www.mtgo.com/decklists/{year}/{month}"

    response = requests.get(archive_url, headers=HEADERS)
    soup = BeautifulSoup(response.text, 'lxml')
    pattern = re.compile(rf"/decklist/(?P<type>.+)-{year}-{month}-{day}(?P<id>\d+)")

    unique_events = {}
    for link in soup.find_all('a', href=True):
        match = pattern.search(link['href'])
        if match:
            event_type = match.group('type')
            if format_filter and format_filter.lower() not in event_type.lower():
                continue

            full_url = "https://www.mtgo.com" + link['href']
            unique_events[full_url] = {
                "name": link.get_text(strip=True),
                "url": full_url,
                "id": match.group('id')
            }
    return list(unique_events.values())


async def get_event_decklists(event_url: str) -> list:
    """
    Scrapes all decklists from a specific MTGO event URL.
    """
    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=HEADERS["User-Agent"])
        page = await context.new_page()

        # Navigate and wait for JS to render
        await page.goto(event_url)
        try:
            # Wait for the main decklist container to load
            await page.wait_for_selector("section.decklist", timeout=15000)
            content = await page.content()
        except Exception as e:
            await browser.close()
            return [{"error": f"Page load timed out: {str(e)}"}]

        await browser.close()
    soup = BeautifulSoup(content, 'lxml')

    decks = []
    deck_containers = soup.find_all('section', class_='decklist')

    for container in deck_containers:
        player_list = container.find_all(class_='decklist-player')
        if player_list:
            player = player_list[0].get_text(strip=True)
            deck_data = {"player": player, "decklist": []}
            for card in container.find_all('a', class_='decklist-card-link'):
                deck_data['decklist'].append(card.string)
            decks.append(deck_data)
    return decks


def format_decklist_output(deck_data):
    """
    Transforms a deck dictionary into a labeled readable format.
    Format:
    Player Name
    Mainboard:
    4 Card Name

    Sideboard:
    1 Sideboard Card
    """
    lines = []

    # 1. Player Header
    lines.append(deck_data.get("player", "Unknown Player"))

    # 2. Mainboard Section
    lines.append("Decklist:")
    for card in deck_data.get("decklist", []):
        lines.append(f"{card}")

    return "\n".join(lines)


@mcp.tool()
async def get_decklists(
        target_date: str,
        format_filter: str | None = None,
        amount: int = 5
):
    """
    Gets all decklists for @target_date for a format or all events.

    Args:
      target_date: Date that we are getting data for.
      format_filter: The MTG format we are getting decklists for.
        If this is None, then we will grab all formats.
      amount: Number of decks to return in the output.

    Returns:
      A string with @amount of decklists that were for the @target_date
      filtered by format using @format_filter.
    """
    events = await get_events(target_date, format_filter)
    decklists = []
    for event in events:
        event_decklists = await get_event_decklists(event['url'])
        decklists.extend(event_decklists)
    sampled_decks = random.sample(
        decklists,
        k=min(amount, len(decklists))
    )
    return '\n'.join(
        format_decklist_output(decklist)
        for decklist in sampled_decks
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")
