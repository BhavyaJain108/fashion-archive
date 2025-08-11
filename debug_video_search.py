#!/usr/bin/env python3
"""
Debug Video Search - Test exactly what the main app is doing
"""

from fashion_video_search import FashionVideoSearchEngine

def test_collection_name_search():
    """Test search using only collection names like the main app does"""
    
    engine = FashionVideoSearchEngine()
    
    # Test with typical collection names that would come from the main app
    test_collection_names = [
        "chanel-spring-2024-ready-to-wear",
        "dior-fall-2023-couture-paris", 
        "versace-spring-summer-2024",
        "gucci-ancora-spring-2024",
        "saint-laurent-spring-2024-paris",
        "balenciaga-fall-2024",
        "prada-resort-2024"
    ]
    
    print("🔍 Testing video search with collection names only (as main app does)")
    print("=" * 70)
    
    for collection_name in test_collection_names:
        print(f"\n📁 Collection: {collection_name}")
        print("-" * 50)
        
        # This is exactly what the main app does:
        # collection_name = self.current_collection_info.get('name', '')
        # best_video = self.video_search_engine.get_best_video(collection_name, collection_url)
        
        best_video = engine.get_best_video(collection_name, "")  # Empty URL like main app might have
        
        if best_video:
            confidence_icon = "🟢" if best_video.confidence > 0.7 else "🟡" if best_video.confidence > 0.4 else "🔴"
            print(f"✅ Found video!")
            print(f"{confidence_icon} Title: {best_video.title}")
            print(f"🔗 URL: {best_video.url}")
            print(f"📊 Confidence: {best_video.confidence:.2f}")
            
            # Show the search query that was generated
            collection_info = engine.parser.parse_collection_info(collection_name)
            query = engine.parser.create_search_query(collection_info)
            print(f"🔍 Search query used: '{query}'")
        else:
            print("❌ No video found (confidence too low)")
            
            # Show what was searched anyway
            collection_info = engine.parser.parse_collection_info(collection_name)
            query = engine.parser.create_search_query(collection_info)
            print(f"🔍 Search query used: '{query}'")
            print(f"📋 Parsed info: {collection_info}")

if __name__ == "__main__":
    test_collection_name_search()