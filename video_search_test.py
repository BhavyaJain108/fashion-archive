#!/usr/bin/env python3
"""
Video Search Test Application
Standalone tester for fashion video search functionality.
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import threading
from typing import List
import webbrowser

try:
    from fashion_video_search import FashionVideoSearchEngine, VideoResult
    from video_player_widget import EnhancedVideoPlayer, VideoPlayerConfig
    MODULES_AVAILABLE = True
except ImportError as e:
    print(f"Required modules not available: {e}")
    MODULES_AVAILABLE = False


class VideoSearchTestWindow:
    """Test window for video search functionality"""
    
    def __init__(self, parent=None):
        self.parent = parent
        self.search_engine = FashionVideoSearchEngine() if MODULES_AVAILABLE else None
        self.current_results = []
        
        self.create_window()
        
    def create_window(self):
        """Create the test window"""
        if self.parent:
            self.window = tk.Toplevel(self.parent)
            self.window.transient(self.parent)
        else:
            self.window = tk.Tk()
            
        self.window.title("Fashion Video Search Tester")
        self.window.geometry("800x700")
        self.window.configure(bg='white')
        
        # Make window resizable
        self.window.grid_rowconfigure(0, weight=1)
        self.window.grid_columnconfigure(0, weight=1)
        
        self.setup_ui()
        
        if not MODULES_AVAILABLE:
            self.show_error("Required modules (fashion_video_search, video_player_widget) not available")
    
    def setup_ui(self):
        """Setup the user interface"""
        main_frame = ttk.Frame(self.window, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        main_frame.grid_rowconfigure(3, weight=1)
        main_frame.grid_columnconfigure(0, weight=1)
        
        # Title
        title_label = ttk.Label(main_frame, text="Fashion Video Search Tester", 
                               font=('Arial', 16, 'bold'))
        title_label.grid(row=0, column=0, columnspan=3, pady=(0, 20))
        
        # Input section
        input_frame = ttk.LabelFrame(main_frame, text="Search Parameters", padding="10")
        input_frame.grid(row=1, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(0, 10))
        input_frame.grid_columnconfigure(1, weight=1)
        
        # Designer name
        ttk.Label(input_frame, text="Designer:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.designer_var = tk.StringVar(value="Chanel")
        self.designer_entry = ttk.Entry(input_frame, textvariable=self.designer_var, width=30)
        self.designer_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        
        # Season
        ttk.Label(input_frame, text="Season:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        self.season_var = tk.StringVar(value="Spring")
        season_combo = ttk.Combobox(input_frame, textvariable=self.season_var, 
                                   values=["Spring", "Summer", "Fall", "Winter", "Resort", "Couture"])
        season_combo.grid(row=1, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(10, 0))
        
        # Year
        ttk.Label(input_frame, text="Year:").grid(row=2, column=0, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        self.year_var = tk.StringVar(value="2024")
        self.year_entry = ttk.Entry(input_frame, textvariable=self.year_var, width=10)
        self.year_entry.grid(row=2, column=1, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        
        # City (optional)
        ttk.Label(input_frame, text="City (optional):").grid(row=3, column=0, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        self.city_var = tk.StringVar(value="Paris")
        city_combo = ttk.Combobox(input_frame, textvariable=self.city_var,
                                 values=["", "Paris", "Milan", "London", "New York"])
        city_combo.grid(row=3, column=1, sticky=(tk.W, tk.E), padx=(0, 10), pady=(10, 0))
        
        # Search button
        self.search_button = ttk.Button(input_frame, text="🔍 Search Videos", 
                                       command=self.search_videos)
        self.search_button.grid(row=0, column=2, rowspan=4, padx=(10, 0))
        
        # Status label
        self.status_var = tk.StringVar(value="Ready to search")
        status_label = ttk.Label(input_frame, textvariable=self.status_var, 
                                font=('Arial', 9), foreground='blue')
        status_label.grid(row=4, column=0, columnspan=3, pady=(10, 0))
        
        # Results section
        results_frame = ttk.LabelFrame(main_frame, text="Search Results", padding="10")
        results_frame.grid(row=2, column=0, columnspan=3, sticky=(tk.W, tk.E), pady=(10, 0))
        results_frame.grid_columnconfigure(0, weight=1)
        
        # Query display
        ttk.Label(results_frame, text="Search Query:", font=('Arial', 9, 'bold')).grid(row=0, column=0, sticky=tk.W)
        self.query_var = tk.StringVar(value="")
        query_label = ttk.Label(results_frame, textvariable=self.query_var, 
                               font=('Arial', 9), foreground='gray', wraplength=700)
        query_label.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # Results list
        self.results_frame = ttk.Frame(results_frame)
        self.results_frame.grid(row=2, column=0, sticky=(tk.W, tk.E))
        self.results_frame.grid_columnconfigure(0, weight=1)
        
        # Detailed view section
        detail_frame = ttk.LabelFrame(main_frame, text="Video Player", padding="10")
        detail_frame.grid(row=3, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(10, 0))
        detail_frame.grid_rowconfigure(0, weight=1)
        detail_frame.grid_columnconfigure(0, weight=1)
        
        if MODULES_AVAILABLE:
            # Video player
            video_config = VideoPlayerConfig(width=600, height=300)
            self.video_player = EnhancedVideoPlayer(detail_frame, video_config)
        else:
            ttk.Label(detail_frame, text="Video player not available - missing dependencies").grid(row=0, column=0)
        
        # Preset buttons
        presets_frame = ttk.Frame(main_frame)
        presets_frame.grid(row=4, column=0, columnspan=3, pady=(10, 0))
        
        ttk.Label(presets_frame, text="Quick Tests:", font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 10))
        
        presets = [
            ("Chanel SS24", "Chanel", "Spring", "2024", "Paris"),
            ("Dior Couture", "Dior", "Couture", "2023", "Paris"),
            ("Versace FW23", "Versace", "Fall", "2023", "Milan"),
            ("Prada Resort", "Prada", "Resort", "2024", "")
        ]
        
        for name, designer, season, year, city in presets:
            btn = ttk.Button(presets_frame, text=name, 
                           command=lambda d=designer, s=season, y=year, c=city: self.load_preset(d, s, y, c))
            btn.pack(side=tk.LEFT, padx=2)
    
    def load_preset(self, designer, season, year, city):
        """Load preset values"""
        self.designer_var.set(designer)
        self.season_var.set(season)
        self.year_var.set(year)
        self.city_var.set(city)
    
    def search_videos(self):
        """Search for videos based on input parameters"""
        if not MODULES_AVAILABLE:
            self.show_error("Search modules not available")
            return
            
        # Get input values
        designer = self.designer_var.get().strip()
        season = self.season_var.get().strip()
        year = self.year_var.get().strip()
        city = self.city_var.get().strip()
        
        if not designer:
            self.show_error("Please enter a designer name")
            return
        
        # Construct collection name
        parts = [designer.lower()]
        if season:
            parts.append(season.lower())
        if year:
            parts.append(year)
        if city:
            parts.append(city.lower())
        
        collection_name = "-".join(parts)
        
        # Update status
        self.status_var.set("Searching...")
        self.search_button.config(state=tk.DISABLED)
        self.clear_results()
        
        def search_thread():
            try:
                # Perform search
                videos = self.search_engine.search_for_collection(collection_name)
                
                # Get the search query that was used
                collection_info = self.search_engine.parser.parse_collection_info(collection_name)
                query = self.search_engine.parser.create_search_query(collection_info)
                
                # Update UI in main thread
                self.window.after(0, lambda: self.display_results(videos, query))
                
            except Exception as e:
                self.window.after(0, lambda: self.search_error(str(e)))
        
        # Start search in background
        threading.Thread(target=search_thread, daemon=True).start()
    
    def display_results(self, videos: List[VideoResult], query: str):
        """Display search results"""
        self.current_results = videos
        self.query_var.set(f"'{query}'")
        
        # Update status
        if videos:
            self.status_var.set(f"Found {len(videos)} videos")
        else:
            self.status_var.set("No videos found")
        
        self.search_button.config(state=tk.NORMAL)
        
        # Display results
        for i, video in enumerate(videos):
            self.create_result_item(i, video)
    
    def create_result_item(self, index: int, video: VideoResult):
        """Create a result item widget"""
        item_frame = ttk.Frame(self.results_frame, relief='solid', borderwidth=1, padding="5")
        item_frame.grid(row=index, column=0, sticky=(tk.W, tk.E), pady=2)
        item_frame.grid_columnconfigure(1, weight=1)
        
        # Confidence score
        confidence_color = 'green' if video.confidence > 0.7 else 'orange' if video.confidence > 0.4 else 'red'
        confidence_label = tk.Label(item_frame, text=f"{video.confidence:.2f}", 
                                   font=('Arial', 10, 'bold'), fg=confidence_color)
        confidence_label.grid(row=0, column=0, padx=(0, 10))
        
        # Video title
        title_text = video.title[:80] + "..." if len(video.title) > 80 else video.title
        title_label = ttk.Label(item_frame, text=title_text, font=('Arial', 10))
        title_label.grid(row=0, column=1, sticky=(tk.W, tk.E))
        
        # Buttons
        btn_frame = ttk.Frame(item_frame)
        btn_frame.grid(row=0, column=2, padx=(10, 0))
        
        play_btn = ttk.Button(btn_frame, text="▶ Play", 
                            command=lambda v=video: self.play_video(v))
        play_btn.pack(side=tk.LEFT, padx=2)
        
        browser_btn = ttk.Button(btn_frame, text="🌐 Browser", 
                               command=lambda url=video.url: webbrowser.open(url))
        browser_btn.pack(side=tk.LEFT, padx=2)
        
        details_btn = ttk.Button(btn_frame, text="ℹ️ Info", 
                               command=lambda v=video: self.show_video_details(v))
        details_btn.pack(side=tk.LEFT, padx=2)
    
    def play_video(self, video: VideoResult):
        """Play video in the embedded player"""
        if MODULES_AVAILABLE and hasattr(self, 'video_player'):
            self.video_player.load_video_with_thumbnail(
                video.url, video.title, video.thumbnail_url
            )
    
    def show_video_details(self, video: VideoResult):
        """Show detailed video information"""
        details = f"""Title: {video.title}
URL: {video.url}
Source: {video.source}
Confidence Score: {video.confidence:.2f}
Thumbnail: {video.thumbnail_url[:50]}{'...' if len(video.thumbnail_url) > 50 else ''}
Duration: {video.duration or 'Unknown'}
Views: {video.view_count or 'Unknown'}"""
        
        messagebox.showinfo("Video Details", details)
    
    def clear_results(self):
        """Clear current results"""
        for widget in self.results_frame.winfo_children():
            widget.destroy()
        self.current_results = []
        self.query_var.set("")
    
    def search_error(self, error_msg: str):
        """Handle search error"""
        self.status_var.set(f"Search error: {error_msg}")
        self.search_button.config(state=tk.NORMAL)
        self.show_error(f"Search failed: {error_msg}")
    
    def show_error(self, message: str):
        """Show error message"""
        messagebox.showerror("Error", message)
    
    def run(self):
        """Run the test window"""
        if not self.parent:  # Only run mainloop if standalone
            self.window.mainloop()


def create_search_test_popup(parent=None):
    """Create and show video search test popup"""
    test_window = VideoSearchTestWindow(parent)
    return test_window


# Standalone test runner
if __name__ == "__main__":
    if not MODULES_AVAILABLE:
        print("Error: Required modules not available")
        print("Make sure fashion_video_search.py and video_player_widget.py are in the same directory")
        exit(1)
    
    # Run standalone test
    app = VideoSearchTestWindow()
    app.run()