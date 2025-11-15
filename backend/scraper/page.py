"""
Page Module
===========

Represents web pages in the scraping system with specialized handling for different page types.
"""


class Page:
    """
    Base class for pages in the scraping system.
    """
    
    def __init__(self):
        """Initialize a Page"""
        pass


class StartingPage(Page):
    """
    Special subclass for the initial entry point of a brand website.
    """
    
    def __init__(self):
        """Initialize a StartingPage"""
        super().__init__()