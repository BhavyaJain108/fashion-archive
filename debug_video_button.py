#!/usr/bin/env python3
"""
Debug Video Button Issues
Check if the video button conditions are being met.
"""

import sys
import os

def check_video_button_conditions():
    """Check all the conditions needed for video button to work"""
    
    print("🔘 Debugging Video Button")
    print("=" * 40)
    
    # Check 1: Video imports
    print("1. Checking video feature imports...")
    try:
        from fashion_video_search import FashionVideoSearchEngine
        from video_player_widget import EnhancedVideoPlayer
        from video_search_test import create_search_test_popup
        print("   ✅ All video modules imported successfully")
        VIDEO_FEATURES_AVAILABLE = True
    except ImportError as e:
        print(f"   ❌ Import error: {e}")
        VIDEO_FEATURES_AVAILABLE = False
        return
    
    # Check 2: Can we create the components?
    print("2. Testing video component creation...")
    try:
        engine = FashionVideoSearchEngine()
        print("   ✅ FashionVideoSearchEngine created")
        
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()  # Hide the window
        
        from video_player_widget import VideoPlayerConfig
        config = VideoPlayerConfig(width=400, height=300)
        player = EnhancedVideoPlayer(root, config)
        print("   ✅ EnhancedVideoPlayer created")
        
        root.destroy()
        
    except Exception as e:
        print(f"   ❌ Component creation error: {e}")
        return
    
    # Check 3: Test the search function directly
    print("3. Testing video search directly...")
    try:
        collection_name = "Adeline-Andre-Couture-Fall-Winter-2011-Paris-Fashion-Week-Runway"
        videos = engine.search_for_collection(collection_name)
        print(f"   ✅ Search completed, found {len(videos)} videos")
        
        if videos:
            best = videos[0]
            print(f"   🎥 Best: {best.title} (confidence: {best.confidence:.2f})")
        
    except Exception as e:
        print(f"   ❌ Search error: {e}")
        return
    
    print("\n✅ All video components are working!")
    print("\nThe issue might be:")
    print("- Video button not properly connected to toggle_video_panel")
    print("- current_collection_info not being set correctly") 
    print("- video_player not initialized in main app")
    print("- Some condition blocking the button handler")

def check_main_app_conditions():
    """Check the specific conditions from the main app"""
    
    print("\n🔍 Checking Main App Conditions")
    print("=" * 40)
    
    # Simulate the exact conditions from fashion_scraper.py
    
    # From __init__:
    print("Simulating main app initialization...")
    try:
        from fashion_video_search import FashionVideoSearchEngine
        from video_player_widget import EnhancedVideoPlayer, VideoPlayerConfig
        VIDEO_FEATURES_AVAILABLE = True
        print("✅ VIDEO_FEATURES_AVAILABLE = True")
    except ImportError:
        VIDEO_FEATURES_AVAILABLE = False
        print("❌ VIDEO_FEATURES_AVAILABLE = False")
        return
    
    # Check video_search_engine creation
    try:
        video_search_engine = FashionVideoSearchEngine()
        print("✅ video_search_engine created")
    except Exception as e:
        print(f"❌ video_search_engine creation failed: {e}")
        return
    
    # Simulate current_collection_info being set (from load_downloaded_images)
    designer_name = "Adeline-Andre-Couture-Fall-Winter-2011-Paris-Fashion-Week-Runway"
    current_collection_info = {
        'name': designer_name,
        'url': '',  # Usually empty
        'designer': designer_name
    }
    print(f"✅ current_collection_info set: {current_collection_info['name'][:30]}...")
    
    # Check toggle_video_panel conditions:
    print("\nChecking toggle_video_panel conditions:")
    
    # if not VIDEO_FEATURES_AVAILABLE or not self.video_player:
    #     return
    has_video_player = True  # Assume it exists
    can_toggle = VIDEO_FEATURES_AVAILABLE and has_video_player
    print(f"   VIDEO_FEATURES_AVAILABLE and video_player: {'✅' if can_toggle else '❌'}")
    
    # Check search_collection_video conditions:
    print("\nChecking search_collection_video conditions:")
    
    # if not VIDEO_FEATURES_AVAILABLE or not self.video_search_engine or not self.current_collection_info:
    #     return
    can_search = VIDEO_FEATURES_AVAILABLE and video_search_engine and current_collection_info
    print(f"   All search conditions met: {'✅' if can_search else '❌'}")
    
    print(f"\n🎯 Button should work: {'✅ YES' if can_toggle and can_search else '❌ NO'}")

if __name__ == "__main__":
    check_video_button_conditions()
    check_main_app_conditions()