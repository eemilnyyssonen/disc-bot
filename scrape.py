# -*- coding: utf-8 -*-
"""
Created on Fri Apr  2 14:26:33 2021
Class for scraping the e-commerce sites products and productpages. 
Uses mainly requests library to get the html.

@author: Eemil Nyyssönen, Espoo, Finland
email: eemil.nyyssonen@aalto.fi
"""


import re
import time
import datetime
import os
import logging
from functools import partial


import requests
import pandas as pd
import numpy as np
from requests_html import HTMLSession, AsyncHTMLSession
from decorators import timer

logger = logging.getLogger(__name__)
# =============================================================================
# Classes to be implemented: Bot: tg bot and defined all the needed functionality
#
# =============================================================================
#  Rough outline:
# 1. Get data in a clear format
# 2. Check if the store has any special offers; e.g. 'huk' in products
#     if true: ---> send alert to TG with some information
#     else sleep(300)
# 3. Update every 5 min in background
#
# Second iteration:
#   implement feature that orders the items if you send command via tg
#   IDEAS:
#       Tell user how many left in stock, color weight etc...
NUM_RESULTS = 100

# Observable class
class OnState(object):
    def __init__(self) -> None:
        self._state = False
        self.observers = []

    @property
    def state(self) -> bool:
        return self._state

    @state.setter
    def state(self, value: bool) -> None:
        self._state = value
        for callback in self.observers:
            logger.info(f'State of the system changed, new state: {value}')
            callback(self._state)
    
    def bind_to(self, callback) -> None:
        logger.info(f'Bound callback: {callback.__name__}')
        self.observers.append(callback)
class Scrape(object):
    def __init__(self, URL: str, targets: list, data: OnState) -> None:
        # Path to url we want to fetch updates from, private
        self._URL = URL

        # Dict to hold the names and prices
        self._results = {}

        # Init html session
        self._session = HTMLSession()

        #self._asession = AsyncHTMLSession()

        # Targets, list of disc name we want alerts for
        self._targets = targets

        self._product_names = set()

        self._data = data
        self._data.bind_to(self.update_state)

        # Have we found the disc?
        self._state = self._data.state

        # When have we last updated?
        self._latest_update = ""
    
    def update_state(self, value) -> None:
        logger.info(f'Global state change to: {value}')
        self._state = value

    def get_state(self) -> bool:
        return self._state

    def mod_targets(self, new_targets: list) -> None:
        """Rewrite the current target list"""
        self._targets = new_targets
        self.update_state(False)

    def add_targets(self, new_targets: list) -> None:
        """Add targets to the existing target list."""
        [self._targets.append(new) for new in new_targets]
        self.update_state(False)

    @timer
    def update_search(self) -> bool:
        """
        make docstring
        """
        logger.info("Update started.")
        # Get html response object
        request = self.get_request()
        logger.info(f"Got response: {request.status_code}")
        # Search for the discs
        self.update_state(self.search_products(request))
        logger.info(f"Search returned with output: {self._state}")
        # Update time
        self._latest_update = self.get_current_time()
        return self._state

    def get_request(self, url: str=None) -> requests.Response:
        """Get content of the url in response object

        Args:
            url ([string], optional): String representation of an URL. Defaults to None.
        Returns:
            r [Response object]
        """
        if url is None:
            url = self._URL + f"?per_page={NUM_RESULTS}"
        # initialize Response object
        r = self._session.get(url)

        return r

    def search_products(self, r: requests.Response) -> bool:
        """
        Search the product page.

        Returns
        -------
        boolean.

        """
        # Targets not in page
        test = [r.html.search(f"{target}") for target in self._targets]
        if not test:
            return False
        # Search query results page
        products = r.html.find(
            ".inner"
        )  # note to self: inner holds the disc sections

        # list where is stored all discs and prices in the page
        discs = {
            inner_class.find(".ProductImage", first=True).attrs["title"]: [
                inner_class.find(".grid-price", first=True).text,
                inner_class.absolute_links.pop(),
            ]
            for inner_class in products
        }  # name: [price, link to disc]

        # Find the  defined targets
        results = {
            key: value
            for target in self._targets
            for key, value in discs.items()
            if re.search(target.lower(), key.lower())
        }  # catch KeyErrors compile( target.lower() ).
        self._results = results

        return (True if results else False)

    @timer
    def get_details(self) -> dict:
        """@dev Get the further details of the already found products.
            The atrributes involves weight, colors and availability.
            All the mentioned information is asynchronously fetched from the product pages of each product.

            Example of the option tag that contains all the information we need:
                <option value="72018">Paino: 173-175g | Väri: Keltavihreä (Saatavilla 21 kpl)</option>

        Returns:
            [type]: [description]
        """
        logger.info('Fetching details...')
        exceptation_attr = (
            "Availability"  # Attribute key, formatting differs from others
        )
        title_class = ".product-title.hidden-sm.hidden-md.hidden-lg"  # Class for getting the name
        element_class = (
            ".FormItem.BuyFormVariationSelect"  # Class of the attributes
        )

        # Get links to the produts we have found
        urls = self._get_urls()
        responses = self.get_async_requests(urls)
        details = {}

        # Iterate over the found url's and find the relevant information
        for r in responses:
            # Get info from html classes in the case of our html
            name = r.html.find(title_class, first=True).text
            element = r.html.find(element_class, first=True)
            options = element.find("option")

            attr_dict = {}  # Temporary dictionary for the attributes
            details[name] = []  # Initialize the value (list) of details dict
            self._product_names.add(name)

            # Iterate over option html classes
            for option in options:
                # Get list of (disc) attributes, in this case name, weight, stamp colour, availability
                attrs = self._parse_option(option)

                for attr in attrs:
                    s = (
                        attr.split(" ")
                        if exceptation_attr in attr
                        else attr.split(": ")
                    )
                    key, val = s[0], s[1]
                    try:
                        attr_dict[key].append(val)
                    except KeyError:
                        attr_dict[key] = [val]

            details[name].append(attr_dict)

        # details is a dictionary consisting of lists of dictionaries of lists lmao
        return details

    def _get_urls(self):
        """Get urls of found discs. Returns a list of urls"""
        try:
            df = self.get_results()
            urls = df["URL"].tolist()
        except Exception as e:
            logger.debug(f"Exception in get_urls: {e.message}")
            return
        return urls

    def _parse_option(self, o) -> str:
        """Parse attribute string from option value found in disc product page. Helper for get_details

        Args:
            o ([type]): [description]

        Returns:
            [type]: [description]
        """
        return (
            str(o.text).replace(")", "").replace("(", "| ").split(" | ")
        )  # paino: {nimi: [saatavuus, väri, stämpin väri]}

    def get_async_requests(self, urls: list) -> list:
        """Get all requests asynchronously using AsyncHTMLSession. Helper function to be deployed in get_details function.

        Args:
            URLs ([list(string)]): List of url:s to be fetched

        Returns:
            [list]: [List of Response objects from each url defined in URLs]
        """

        # async def get(url):
        #   r = await self._asession.get(url)
        #  return r

        # getter_dict = {f'get_{i}':partial(get, url = u ) for i,u in enumerate(urls)}

        # results = self._asession.run( *list(getter_dict.values()) )

        return [self._session.get(url) for url in urls]

    def get_results(self) -> pd.DataFrame:
        """
        Get results from the product page in dataframe, including disc and price

        Returns
        -------
        pd.DataFrame

        """
        # Make dataframe from dictionary
        df = pd.DataFrame
        if self._results:
            df = pd.DataFrame.from_dict(
                data=self._results, orient="index", columns=["Price", "URL"]
            )
        return df

    def get_current_time(self) -> str:
        """Get the current time formatted to string.

        Returns:
            [string]: [String describing the current time in format dd.mm.yyyy-hh.mm.ss]
        """
        return datetime.datetime.now().strftime('"%d.%m.%Y-%H.%M.%S"')

    def description(self) -> str:
        current_time = self.get_current_time()
        if self.current_state():
            return f'\nTarget(s) found at {current_time}\nApplicable results are:\n {self.get_results().to_markdown(tablefmt="grid")}'  # Better looking format for console logging
        elif self._latest_update:
            return f"System running, last update at {self._latest_update}"
        else:
            return (
                f"System up, no updates yet\."
                + "=" * 50
                + f"Looking for targets: {str(self._targets)}"
            )

    def __str__(self):
        """
        Text presentation of the current state of the scraper, used for debugging purposes.

        Returns
        -------
        str:   String containing information about the current state

        """
        return self.description()

    def _new_session(self):
        self._session = HTMLSession()


# =============================================================================
# Updates for tg bot:
#   -update command for updating the target products
#   -more: more info
#   -less: less info
#   -order: order products
#   -frequency: set frequency for updates
#
# =============================================================================
