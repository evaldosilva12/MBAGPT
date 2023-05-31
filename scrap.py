# scrap.py
import requests

def scrape_webpage(url):
    r = requests.get(url)
    r.raise_for_status()

    return r.text
