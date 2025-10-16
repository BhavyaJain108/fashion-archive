#!/usr/bin/env python3
"""
Product Service
===============

Business logic for product management operations.
"""

from typing import Dict, Any, List, Tuple
from ..models.brand import Brand
from ..models.product import Product, Collection
from ..utils.id_generator import generate_product_id
from ..brand_collection_manager import BrandCollectionManager


class ProductService:
    """Service class for product operations"""
    
    def __init__(self):
        self.collection_manager = BrandCollectionManager()
    
    def get_brand_products(self, brand: Brand) -> Tuple[List[Product], Dict[str, Collection]]:
        """
        Get all products for a brand organized by collection
        
        Returns:
            Tuple of (all_products_list, collections_dict)
        """
        brand_products = self.collection_manager.get_brand_products(brand.slug)
        
        all_products = []
        collections_data = {}
        
        for collection_name, collection_products in brand_products.items():
            formatted_products = []
            
            for product in collection_products:
                product_id = generate_product_id(
                    product.get('url', ''), 
                    product.get('name', '')
                )
                
                product_obj = Product.from_collection_data(
                    product, collection_name, product_id
                )
                
                formatted_products.append(product_obj)
                all_products.append(product_obj)
            
            collection_obj = Collection(
                name=collection_name,
                products=formatted_products,
                count=len(formatted_products)
            )
            collections_data[collection_name] = collection_obj
        
        return all_products, collections_data
    
    def get_products_by_collection(self, brand: Brand, collection_name: str) -> List[Product]:
        """Get products for a specific collection"""
        brand_products = self.collection_manager.get_brand_products(brand.slug)
        
        if collection_name not in brand_products:
            return []
        
        products = []
        for product in brand_products[collection_name]:
            product_id = generate_product_id(
                product.get('url', ''), 
                product.get('name', '')
            )
            
            product_obj = Product.from_collection_data(
                product, collection_name, product_id
            )
            products.append(product_obj)
        
        return products
    
    def add_product_favorite(self, product_id: int, notes: str = '') -> Dict[str, Any]:
        """Add a product to favorites - Not implemented with new storage system"""
        return {
            'success': False,
            'message': 'Favorites not yet implemented with new storage system'
        }
    
    def get_brand_collections_only(self, brand: Brand) -> List[Dict[str, Any]]:
        """
        Get only collection information for a brand (no products)
        
        Returns:
            List of collection metadata with counts
        """
        brand_products = self.collection_manager.get_brand_products(brand.slug)
        
        collections = []
        for collection_name, collection_products in brand_products.items():
            collection_info = {
                'name': collection_name,
                'slug': collection_name.lower().replace(' ', '-'),
                'count': len(collection_products),
                'url': f'/api/brands/{brand.id}/collections/{collection_name.lower().replace(" ", "-")}/products'
            }
            collections.append(collection_info)
        
        return collections
    
    def get_brand_favorites(self) -> List[Dict[str, Any]]:
        """Get all favorite products from brands - Not implemented with new storage system"""
        return []