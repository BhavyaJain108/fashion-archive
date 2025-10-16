#!/usr/bin/env python3
"""
Product Data Models
==================

Standardized data structures for product information.
"""

from typing import Dict, Any, List, Optional
from dataclasses import dataclass


@dataclass
class Product:
    """Product data model"""
    id: int
    name: str
    url: str
    image_url: str
    price: Optional[str] = None
    collection: str = ''
    images: List[str] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.images is None:
            self.images = [self.image_url] if self.image_url else []
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            'id': self.id,
            'name': self.name,
            'url': self.url,
            'image_url': self.image_url,
            'price': self.price,
            'collection': self.collection,
            'images': self.images,
            'metadata': self.metadata
        }
    
    @classmethod
    def from_collection_data(cls, product_data: Dict[str, Any], collection_name: str, product_id: int) -> 'Product':
        """Create Product instance from collection manager data"""
        return cls(
            id=product_id,
            name=product_data.get('name', 'Unknown Product'),
            url=product_data.get('url', ''),
            image_url=product_data.get('image_url', ''),
            price=product_data.get('price'),
            collection=collection_name,
            images=[product_data.get('image_url', '')] if product_data.get('image_url') else [],
            metadata={
                'collection_name': collection_name,
                'discovered_at': product_data.get('discovered_at')
            }
        )


@dataclass
class Collection:
    """Collection data model"""
    name: str
    products: List[Product]
    count: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses"""
        return {
            'name': self.name,
            'products': [product.to_dict() for product in self.products],
            'count': self.count
        }