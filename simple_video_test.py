#!/usr/bin/env python3
"""
Simple Video Retriever Test
A standalone script to test video search functionality independently.
"""

import sys
import webbrowser
from fashion_video_search import FashionVideoSearchEngine

def simple_video_search(designer, season, year, city=""):
    """
    Simple function to search for fashion videos
    
    Args:
        designer (str): Designer name (e.g., "Chanel")
        season (str): Season (e.g., "Spring", "Fall", "Couture")
        year (str): Year (e.g., "2024")
        city (str): City (optional, e.g., "Paris")
    
    Returns:
        List of video results
    """
    
    # Create search engine
    engine = FashionVideoSearchEngine()
    
    # Construct collection name
    parts = [designer.lower()]
    if season:
        parts.append(season.lower())
    if year:
        parts.append(year)
    if city:
        parts.append(city.lower())
    
    collection_name = "-".join(parts)
    
    print(f"🔍 Searching for: {collection_name}")
    print("=" * 50)
    
    # Search for videos
    videos = engine.search_for_collection(collection_name)
    
    if not videos:
        print("❌ No videos found")
        return []
    
    print(f"✅ Found {len(videos)} videos:")
    print()
    
    for i, video in enumerate(videos, 1):
        confidence_emoji = "🟢" if video.confidence > 0.7 else "🟡" if video.confidence > 0.4 else "🔴"
        print(f"{i}. {confidence_emoji} [{video.confidence:.2f}] {video.title}")
        print(f"   🔗 {video.url}")
        if video.thumbnail_url:
            print(f"   🖼️ Thumbnail: {video.thumbnail_url[:50]}...")
        print()
    
    return videos

def interactive_search():
    """Interactive video search"""
    print("🎬 Fashion Video Search Tool")
    print("=" * 50)
    
    while True:
        print("\nEnter search details (or 'quit' to exit):")
        
        designer = input("👗 Designer: ").strip()
        if designer.lower() in ['quit', 'exit', 'q']:
            break
            
        season = input("🌸 Season (Spring/Fall/Couture/etc.): ").strip()
        year = input("📅 Year: ").strip()
        city = input("🏙️ City (optional): ").strip()
        
        if not designer:
            print("❌ Designer name is required!")
            continue
        
        print()
        videos = simple_video_search(designer, season, year, city)
        
        if videos:
            while True:
                try:
                    choice = input(f"\n🎥 Open video (1-{len(videos)}) or press Enter to search again: ").strip()
                    if not choice:
                        break
                    
                    index = int(choice) - 1
                    if 0 <= index < len(videos):
                        video = videos[index]
                        print(f"🌐 Opening: {video.title}")
                        webbrowser.open(video.url)
                        break
                    else:
                        print(f"❌ Please enter a number between 1 and {len(videos)}")
                except ValueError:
                    print("❌ Please enter a valid number")

def test_presets():
    """Test with preset collections"""
    presets = [
        ("Chanel", "Spring", "2024", "Paris"),
        ("Dior", "Couture", "2023", "Paris"),
        ("Versace", "Fall", "2023", "Milan"),
        ("Prada", "Resort", "2024", ""),
        ("Saint Laurent", "Spring", "2024", "Paris")
    ]
    
    print("🧪 Testing preset collections:")
    print("=" * 50)
    
    for designer, season, year, city in presets:
        print(f"\n🎯 Testing: {designer} {season} {year}" + (f" {city}" if city else ""))
        videos = simple_video_search(designer, season, year, city)
        
        if videos:
            best_video = videos[0]
            print(f"   🏆 Best match: {best_video.title} (confidence: {best_video.confidence:.2f})")
        
        print("-" * 30)

if __name__ == "__main__":
    print("Fashion Video Retriever Test")
    print("Choose an option:")
    print("1. Interactive search")
    print("2. Test presets")
    print("3. Quick search")
    
    choice = input("\nEnter choice (1-3): ").strip()
    
    if choice == "1":
        interactive_search()
    elif choice == "2":
        test_presets()
    elif choice == "3":
        # Quick search with command line args
        if len(sys.argv) >= 3:
            designer = sys.argv[1]
            season = sys.argv[2] if len(sys.argv) > 2 else ""
            year = sys.argv[3] if len(sys.argv) > 3 else ""
            city = sys.argv[4] if len(sys.argv) > 4 else ""
            
            videos = simple_video_search(designer, season, year, city)
            if videos:
                print(f"\n🎥 Opening best match: {videos[0].title}")
                webbrowser.open(videos[0].url)
        else:
            print("Usage for quick search: python simple_video_test.py <designer> <season> <year> [city]")
            print("Example: python simple_video_test.py Chanel Spring 2024 Paris")
    else:
        print("❌ Invalid choice")