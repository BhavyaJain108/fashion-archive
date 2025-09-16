"""
Product Module
==============

Represents a product discovered during scraping.
"""


class Product:
    """
    Represents a fashion product discovered during scraping.
    
    Core attributes:
    - name: Product name/title
    - url: Product page URL
    - image: Primary product image URL
    """
    
    def __init__(self, name: str, url: str, image: str):
        """
        Initialize a Product
        
        Args:
            name: Product name/title
            url: Product page URL
            image: Primary product image URL
        """
        self.name = name
        self.url = url
        self.image = image
        
        # Placeholder for other metadata to be added later
        self.metadata = {}