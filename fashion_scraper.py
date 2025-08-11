#!/usr/bin/env python3
"""
Fashion Archive System - Main Application

An intelligent fashion show archive system designed to preserve and organize 
fashion history from major fashion weeks around the world.

This module provides the main GUI application for browsing, downloading, and 
viewing fashion collections with AI-powered video verification.

Author: Fashion Archive Team
License: MIT
"""

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse
import threading
from PIL import Image, ImageTk
import io
import webbrowser

# Import video modules
try:
    from claude_video_verifier import EnhancedFashionVideoSearch
    from video_search_test import create_search_test_popup
    VIDEO_FEATURES_AVAILABLE = True
except ImportError as e:
    print(f"Video features not available: {e}")
    VIDEO_FEATURES_AVAILABLE = False

class FashionScraper:
    """
    Main Fashion Archive System GUI Application
    
    A comprehensive fashion show archiving interface that provides:
    - Season and collection browsing
    - High-quality image downloading and gallery viewing  
    - AI-powered video search and verification
    - Professional video playback with timeline controls
    - Intelligent content organization and cleanup
    
    Attributes:
        root: Main tkinter window
        current_images: List of currently loaded image paths
        current_video_path: Path to currently available video
        video_player_window: Reference to video player window
        video_search_engine: Claude AI-powered video search system
    """
    
    def __init__(self, root):
        """
        Initialize the Fashion Archive System GUI
        
        Args:
            root: Main tkinter root window
        """
        self.root = root
        self.root.title("Fashion Week Archive Browser")
        self.root.geometry("1200x800")
        
        self.base_url = "https://nowfashion.com"
        self.seasons_url = "https://nowfashion.com/fashion-week-seasons/"
        
        # Headers to avoid 403 errors
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
        
        # Set up cleanup on window close
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.setup_menu()
        self.setup_ui()
        self.load_seasons()
    
    def setup_menu(self):
        """Setup the menu bar"""
        menubar = tk.Menu(self.root)
        self.root.config(menu=menubar)
        
        # Tools menu
        tools_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Tools", menu=tools_menu)
        
        if VIDEO_FEATURES_AVAILABLE:
            tools_menu.add_command(label="Video Search Tester", command=self.open_video_test)
            tools_menu.add_separator()
        
        tools_menu.add_command(label="About", command=self.show_about)
    
    def open_video_test(self):
        """Open video search test popup"""
        if VIDEO_FEATURES_AVAILABLE:
            try:
                create_search_test_popup(self.root)
            except Exception as e:
                print(f"Error opening video test: {e}")
        else:
            tk.messagebox.showwarning("Not Available", "Video search features are not available")
    
    def show_about(self):
        """Show about dialog"""
        about_text = """Fashion Week Archive Browser
        
A comprehensive tool for browsing fashion week collections with:
• Season and designer browsing
• Image gallery with hover effects  
• Magnification and zoom features
• Video search and streaming (when available)

Features:
- Progressive column reveal (1→2→3)
- Gallery view with 4-column layout
- Smart video search for runway shows
- Trackpad scrolling support
- Interactive image hover effects"""

        tk.messagebox.showinfo("About", about_text)
    
    def setup_ui(self):
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Title
        title_label = ttk.Label(main_frame, text="Fashion Week Archive Browser", 
                               font=('Arial', 16, 'bold'))
        title_label.pack(pady=(0, 20))
        
        # Loading label
        self.loading_label = ttk.Label(main_frame, text="Loading seasons...")
        self.loading_label.pack(pady=20)
        
        # Create main container
        self.main_container = ttk.Frame(main_frame)
        # Don't pack initially - will pack when seasons load
        
        # Create all frames but don't pack middle/right initially
        self.left_frame = ttk.Frame(self.main_container, width=300)
        self.left_frame.pack_propagate(False)
        
        self.middle_frame = ttk.Frame(self.main_container, width=400) 
        self.middle_frame.pack_propagate(False)
        
        self.right_frame = ttk.Frame(self.main_container)
        
        # Setup frames
        self.setup_seasons_frame(self.left_frame)
        self.setup_collections_frame(self.middle_frame)
        self.setup_image_viewer_frame(self.right_frame)
    
    def show_column2(self):
        """Show collections column"""
        if not self.column2_activated:
            self.column2_activated = True
            self.middle_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(5, 5))
    
    def show_column3(self):
        """Show images column"""  
        if not self.column3_activated:
            self.column3_activated = True
            self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
    def setup_seasons_frame(self, parent_frame):
        # Title for left column
        seasons_title = ttk.Label(parent_frame, text="Fashion Week Seasons", 
                                 font=('Arial', 12, 'bold'))
        seasons_title.pack(pady=(0, 10))
        
        
        # Seasons listbox with scrollbar
        list_frame = ttk.Frame(parent_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        self.seasons_listbox = tk.Listbox(list_frame, font=('Arial', 9), width=35)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.seasons_listbox.yview)
        self.seasons_listbox.config(yscrollcommand=scrollbar.set)
        
        self.seasons_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.seasons_listbox.bind('<Button-1>', self.on_season_select)
        self.seasons_listbox.bind('<Double-Button-1>', self.on_season_select)
        
        # Load collections button
        button_frame = ttk.Frame(parent_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.load_collections_btn = ttk.Button(button_frame, text="View Collections", 
                                              command=self.load_selected_season)
        self.load_collections_btn.pack()
    
    def setup_collections_frame(self, parent_frame):
        # Header frame
        header_frame = ttk.Frame(parent_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.collections_title = ttk.Label(header_frame, text="", 
                                          font=('Arial', 12, 'bold'))
        self.collections_title.pack(side=tk.LEFT)
        
        # Collections listbox with scrollbar (similar to seasons)
        list_frame = ttk.Frame(parent_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        self.collections_listbox = tk.Listbox(list_frame, font=('Arial', 9))
        collections_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.collections_listbox.yview)
        self.collections_listbox.config(yscrollcommand=collections_scrollbar.set)
        
        self.collections_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        collections_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.collections_listbox.bind('<Button-1>', self.on_designer_select)
        self.collections_listbox.bind('<Double-Button-1>', self.on_designer_select)
        
        # Store collections data
        self.current_collections = []
    
    def setup_image_viewer_frame(self, parent_frame):
        # Header frame
        header_frame = ttk.Frame(parent_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.image_title = ttk.Label(header_frame, text="Image Viewer", 
                                    font=('Arial', 12, 'bold'))
        self.image_title.pack(side=tk.LEFT)
        
        # Status label
        self.image_status = ttk.Label(header_frame, text="Select a designer to view images")
        self.image_status.pack(side=tk.RIGHT)
        
        # Top controls frame (for magnify and gallery buttons)
        top_controls_frame = ttk.Frame(parent_frame)
        top_controls_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Configure button style for uniform height
        style = ttk.Style()
        style.configure('Square.TButton', padding=(10, 10))
        
        # Gallery button on the left
        self.gallery_button = ttk.Button(top_controls_frame, text="gallery", 
                                        command=self.toggle_gallery_view,
                                        state=tk.DISABLED)
        self.gallery_button.pack(side=tk.LEFT)
        
        # Video button next to gallery - shows video player when available
        if VIDEO_FEATURES_AVAILABLE:
            self.video_button = ttk.Button(top_controls_frame, text="📹", 
                                          command=self.toggle_video_player,
                                          state=tk.DISABLED)
            self.video_button.pack(side=tk.LEFT, padx=(5, 0))
        
        # Magnifying glass button on the right - square shape
        self.zoom_button = ttk.Button(top_controls_frame, text="✕", width=3,
                                     style='Square.TButton',
                                     command=self.cycle_zoom_mode, state=tk.DISABLED)
        self.zoom_button.pack(side=tk.RIGHT)
        
        # Image display area
        self.image_frame = ttk.Frame(parent_frame)
        self.image_frame.pack(fill=tk.BOTH, expand=True)
        
        self.image_label = ttk.Label(self.image_frame, text="No images loaded")
        self.image_label.pack(expand=True)
        
        # Video functionality is console-only - no UI components needed
        
        # Bottom navigation frame (below image/video)
        nav_frame = ttk.Frame(parent_frame)
        nav_frame.pack(fill=tk.X, pady=(10, 0))
        
        self.prev_button = ttk.Button(nav_frame, text="◀ Previous", 
                                     command=self.prev_image, state=tk.DISABLED)
        self.prev_button.pack(side=tk.LEFT)
        
        self.image_counter = ttk.Label(nav_frame, text="")
        self.image_counter.pack(side=tk.LEFT, padx=(10, 0))
        
        self.next_button = ttk.Button(nav_frame, text="Next ▶", 
                                     command=self.next_image, state=tk.DISABLED)
        self.next_button.pack(side=tk.RIGHT)
        
        # Image data
        self.current_images = []
        self.current_image_index = 0
        self.current_download_folder = None
        
        # Download state management
        self.is_downloading = False
        self.last_selected_collection = None
        
        # Magnifying glass state management
        self.zoom_mode = 0  # 0=off, 1=2x, 2=3x
        self.zoom_window = None
        self.mouse_tracking = False
        
        # Gallery view state management
        self.gallery_mode = False
        self.gallery_frame = None
        self.gallery_canvas = None
        self.gallery_scrollbar = None
        self.gallery_inner_frame = None
        self.gallery_image_buttons = []
        self.gallery_title_label = None
        self.current_designer_name = ""
        
        # Progressive column reveal flags
        self.column2_activated = False  # Collections column
        self.column3_activated = False  # Images column
        
        # Video functionality - console only
        self.current_collection_info = None
        self.current_video_path = None  # Track downloaded video path
        self.video_player_window = None  # Track video player window
        
        if VIDEO_FEATURES_AVAILABLE:
            self.video_search_engine = EnhancedFashionVideoSearch()
        else:
            self.video_search_engine = None
        
        # Bind arrow keys
        parent_frame.bind('<Left>', lambda e: self.prev_image())
        parent_frame.bind('<Right>', lambda e: self.next_image())
        parent_frame.focus_set()
    
    def load_seasons(self):
        def fetch_seasons():
            try:
                response = requests.get(self.seasons_url, headers=self.headers, timeout=10)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')
                
                # Find all links that look like fashion week seasons
                links = soup.find_all('a', href=True)
                self.season_links = []
                
                for link in links:
                    href = link.get('href')
                    text = link.get_text().strip()
                    
                    # Look for collection URLs
                    if href and '/fashion/collections/' in href:
                        full_url = urljoin(self.base_url, href)
                        if text and len(text) > 5:  # Filter out empty or very short texts
                            self.season_links.append((text, full_url))
                
                # Remove duplicates and sort
                self.season_links = list(set(self.season_links))
                self.season_links.sort(key=lambda x: x[0])
                
                # Update UI in main thread
                self.root.after(0, self.update_seasons_ui)
                
            except Exception as e:
                error_msg = f"Error loading seasons: {str(e)}"
                self.root.after(0, lambda: self.show_error(error_msg))
        
        # Start loading in background thread
        threading.Thread(target=fetch_seasons, daemon=True).start()
    
    def update_seasons_ui(self):
        self.loading_label.pack_forget()
        # Pack main container and left frame
        self.main_container.pack(fill=tk.BOTH, expand=True)
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        
        # Populate listbox
        self.seasons_listbox.delete(0, tk.END)
        for text, url in self.season_links:
            self.seasons_listbox.insert(tk.END, text)
    
    
    def on_season_select(self, event):
        self.load_selected_season()
    
    def load_selected_season(self):
        selection = self.seasons_listbox.curselection()
        if not selection:
            return
        
        index = selection[0]
        season_text, season_url = self.season_links[index]
        
        # Show collections column
        self.show_column2()
        
        # Set the season name as collections title
        self.collections_title.config(text=season_text)
        self.collections_listbox.delete(0, tk.END)
        self.collections_listbox.insert(tk.END, "Loading designer collections...")
        
        def fetch_collections():
            try:
                collections = []
                page = 1
                
                while True:
                    # Construct URL for current page
                    if page == 1:
                        current_url = season_url
                    else:
                        current_url = f"{season_url.rstrip('/')}/page/{page}/"
                    
                    response = requests.get(current_url, headers=self.headers, timeout=10)
                    
                    # Handle 404 as end of pagination
                    if response.status_code == 404:
                        print(f"Reached end of pagination (404) at page {page}")
                        break
                    
                    response.raise_for_status()
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Look specifically for h2 elements with wp-block-post-title class containing designer links
                    h2_elements = soup.find_all('h2', class_='wp-block-post-title')
                    
                    if not h2_elements:
                        # No more collections found, break
                        break
                    
                    page_collections = []
                    for h2 in h2_elements:
                        link = h2.find('a', href=True)
                        if link:
                            href = link.get('href')
                            designer_text = link.get_text().strip()
                            
                            if href and designer_text:
                                page_collections.append({
                                    'designer': designer_text,
                                    'photos': '',
                                    'date': '',
                                    'url': href,
                                    'text': designer_text
                                })
                    
                    if not page_collections:
                        # No collections found on this page, break
                        break
                    
                    collections.extend(page_collections)
                    
                    # Stream results to UI immediately
                    self.root.after(0, lambda p=page, c=len(collections), pc=page_collections: self.stream_collections_update(p, c, pc))
                    
                    # Check for various pagination patterns
                    has_next_page = False
                    
                    # Method 1: Look for "Next" text link
                    next_link = soup.find('a', string=re.compile(r'next|Next', re.IGNORECASE))
                    if next_link:
                        has_next_page = True
                        print(f"Found 'Next' link: {next_link}")
                    
                    # Method 2: Look for pagination with numbered links
                    if not has_next_page:
                        pagination_area = soup.find('nav', class_=re.compile(r'pagination|nav-links')) or soup.find('div', class_=re.compile(r'pagination|nav-links'))
                        if pagination_area:
                            # Look for a link to the next page number
                            next_page_link = pagination_area.find('a', href=re.compile(f'/page/{page + 1}'))
                            if next_page_link:
                                has_next_page = True
                                print(f"Found next page link in pagination: {next_page_link}")
                    
                    # Method 3: Look for arrow-based navigation (›, →, etc.)
                    if not has_next_page:
                        arrow_next = soup.find('a', string=re.compile(r'[›→]|&gt;|&#8250;'))
                        if arrow_next:
                            has_next_page = True
                            print(f"Found arrow next link: {arrow_next}")
                    
                    # Method 4: Check if we got fewer results than expected (might indicate last page)
                    # If this page has significantly fewer items than previous pages, might be last page
                    if not has_next_page and len(page_collections) > 0:
                        # Continue to next page anyway if we got collections (naive approach)
                        has_next_page = True
                        print(f"No pagination found but got {len(page_collections)} collections, trying next page")
                    
                    if not has_next_page:
                        print(f"No more pages found after page {page}")
                        break
                    
                    page += 1
                
                # If no collections found at all, try fallback method on first page
                if len(collections) == 0:
                    response = requests.get(season_url, headers=self.headers, timeout=10)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.content, 'html.parser')
                    
                    # Look for any links that might contain fashion show information
                    fashion_links = soup.find_all('a', href=re.compile(r'fashion|show|collection', re.I))
                    
                    for link in fashion_links:
                        href = link.get('href')
                        text = link.get_text().strip()
                        
                        if href and text and len(text) > 3:
                            full_url = urljoin(self.base_url, href)
                            collections.append({
                                'designer': text,
                                'photos': '',
                                'date': '',
                                'url': full_url,
                                'text': text
                            })
                
                # Remove duplicates based on URL
                seen_urls = set()
                unique_collections = []
                for collection in collections:
                    if collection['url'] not in seen_urls:
                        seen_urls.add(collection['url'])
                        unique_collections.append(collection)
                
                # Sort by designer name
                unique_collections.sort(key=lambda x: x['designer'])
                
                # Update UI
                self.root.after(0, lambda: self.update_collections_ui(unique_collections, season_url))
                
            except Exception as e:
                error_msg = str(e)
                self.root.after(0, lambda: self.show_collections_error(error_msg))
        
        threading.Thread(target=fetch_collections, daemon=True).start()
    
    def update_collections_ui(self, collections, season_url):
        # Clear and populate the collections listbox
        self.collections_listbox.delete(0, tk.END)
        self.current_collections = collections
        
        if not collections:
            self.collections_listbox.insert(tk.END, "No designer shows found")
            return
        
        # Add each designer to the listbox (like directory listing)
        for show in collections:
            # Format like a directory: "📁 Designer Name"
            display_name = f"📁 {show['designer']}"
            self.collections_listbox.insert(tk.END, display_name)
    
    def on_designer_select(self, event):
        """Handle designer selection and download images"""
        selection = self.collections_listbox.curselection()
        if not selection or not self.current_collections:
            return
        
        index = selection[0]
        if index >= len(self.current_collections):
            return
            
        selected_collection = self.current_collections[index]
        
        # Prevent multiple simultaneous downloads
        if self.is_downloading:
            print(f"Download already in progress, ignoring selection")
            return
            
        # Check if this is the same collection as last selected
        if self.last_selected_collection and self.last_selected_collection['url'] == selected_collection['url']:
            print(f"Same collection selected, ignoring duplicate request")
            return
            
        print(f"Selected collection: {selected_collection['designer']} - {selected_collection['url']}")
        self.last_selected_collection = selected_collection
        self.last_selected_collection_url = selected_collection['url']  # Store URL for video search
        
        # Close existing video player when new show is selected
        if self.video_player_window and self.video_player_window.winfo_exists():
            self.close_video_player()
        
        # Clear current video path and disable button
        self.current_video_path = None
        if VIDEO_FEATURES_AVAILABLE and hasattr(self, 'video_button'):
            self.video_button.config(state=tk.DISABLED)
        
        # Clear videos folder for new collection
        self.clear_videos_folder()
        
        # Start video download in parallel with image download
        self.start_video_download(selected_collection)
        
        self.download_and_display_images(selected_collection)
    
    def download_and_display_images(self, collection):
        """Download images for selected collection and display them"""
        from image_downloader import ImageDownloader, DownloadConfig
        import shutil
        from pathlib import Path
        
        # Set downloading state
        self.is_downloading = True
        
        # Clean up previous downloads first
        self.cleanup_previous_downloads()
        
        # Clear current images immediately
        self.current_images = []
        self.current_image_index = 0
        
        # Update UI to show downloading status
        self.image_status.config(text="Downloading images...")
        self.image_title.config(text=f"Downloading: {collection['designer']}")
        self.image_label.config(image="", text="Downloading images...")
        self.image_counter.config(text="")
        
        def download_images():
            try:
                # Create download config
                config = DownloadConfig(
                    url=collection['url'],
                    output_dir="downloads",
                    max_images=100,  # Reasonable limit
                    delay=0.5  # Fast download
                )
                
                # Download images
                downloader = ImageDownloader(config)
                downloaded_files = downloader.download_all()
                
                # Run organization on downloaded files
                if downloaded_files:
                    try:
                        from collection_organizer import CollectionOrganizer
                        
                        # Extract collection info from URL
                        url_parts = collection['url'].strip('/').split('/')
                        collection_name = url_parts[-1] if url_parts else ""
                        
                        # Use URL-based organization
                        organizer = CollectionOrganizer(config.output_dir)
                        result = organizer.organize_folder_with_url_info(collection_name, dry_run=False)
                        print(f"Organization result: {result}")
                    except Exception as e:
                        print(f"Organization error: {e}")
                
                # Store current downloads folder for cleanup
                self.current_download_folder = config.output_dir
                
                # Update UI in main thread
                self.root.after(0, lambda: self.load_downloaded_images(downloaded_files, collection['designer']))
                
            except Exception as e:
                error_msg = str(e)
                self.root.after(0, lambda: self.show_download_error(error_msg))
            finally:
                # Clear downloading state
                self.is_downloading = False
        
        # Start download in background thread
        threading.Thread(target=download_images, daemon=True).start()
    
    def cycle_zoom_mode(self):
        """Cycle through zoom modes: Off -> 2x -> 3x -> Off"""
        self.zoom_mode = (self.zoom_mode + 1) % 3
        
        if self.zoom_mode == 0:  # Off
            self.zoom_button.config(text="✕")
            self.disable_magnification()
        elif self.zoom_mode == 1:  # 2x
            self.zoom_button.config(text="2×")
            self.enable_magnification(2)
        elif self.zoom_mode == 2:  # 3x
            self.zoom_button.config(text="3×")
            self.enable_magnification(3)
    
    def enable_magnification(self, zoom_level):
        """Enable magnification with specified zoom level"""
        if not self.current_images:
            return
            
        self.mouse_tracking = True
        
        # Bind mouse events to image label
        self.image_label.bind('<Motion>', lambda e: self.on_mouse_move(e, zoom_level))
        self.image_label.bind('<Leave>', self.on_mouse_leave)
        
        print(f"Magnification enabled at {zoom_level}x zoom")
    
    def disable_magnification(self):
        """Disable magnification and hide zoom window"""
        self.mouse_tracking = False
        
        # Unbind mouse events
        self.image_label.unbind('<Motion>')
        self.image_label.unbind('<Leave>')
        
        # Hide and destroy zoom window if it exists
        if self.zoom_window:
            self.zoom_window.destroy()
            self.zoom_window = None
            
        print("Magnification disabled")
    
    def on_mouse_move(self, event, zoom_level):
        """Handle mouse movement over image for magnification"""
        if not self.mouse_tracking or not hasattr(self.image_label, 'image') or not self.image_label.image:
            return
            
        # Get mouse position relative to image label
        mouse_x = event.x
        mouse_y = event.y
        
        # Get the actual image size and position
        try:
            # Get the PIL image from the PhotoImage
            pil_image = self.get_current_pil_image()
            if not pil_image:
                return
                
            # Calculate the actual image position within the label
            label_width = self.image_label.winfo_width()
            label_height = self.image_label.winfo_height()
            img_width, img_height = pil_image.size
            
            # Calculate the scale and position of the image within the label
            scale_x = label_width / img_width
            scale_y = label_height / img_height
            scale = min(scale_x, scale_y)
            
            # Actual displayed image size
            display_width = int(img_width * scale)
            display_height = int(img_height * scale)
            
            # Image position within label (centered)
            img_x = (label_width - display_width) // 2
            img_y = (label_height - display_height) // 2
            
            # Check if mouse is actually over the image
            if (mouse_x < img_x or mouse_x > img_x + display_width or 
                mouse_y < img_y or mouse_y > img_y + display_height):
                return
            
            # Convert mouse position to image coordinates
            img_mouse_x = int((mouse_x - img_x) / scale)
            img_mouse_y = int((mouse_y - img_y) / scale)
            
            # Show magnification window
            self.show_zoom_window(pil_image, img_mouse_x, img_mouse_y, zoom_level, 
                                img_x, img_y, display_width, display_height)
            
        except Exception as e:
            print(f"Error in mouse move: {e}")
    
    def on_mouse_leave(self, event):
        """Hide zoom window when mouse leaves image"""
        if self.zoom_window:
            self.zoom_window.destroy()
            self.zoom_window = None
    
    def get_current_pil_image(self):
        """Get the current PIL image"""
        if not self.current_images or self.current_image_index >= len(self.current_images):
            return None
            
        try:
            from PIL import Image
            image_path = self.current_images[self.current_image_index]
            return Image.open(image_path)
        except Exception as e:
            print(f"Error loading PIL image: {e}")
            return None
    
    def show_zoom_window(self, pil_image, img_mouse_x, img_mouse_y, zoom_level, img_x, img_y, display_width, display_height):
        """Show magnification window at mouse position"""
        try:
            # Define magnification window size
            zoom_window_size = 150
            crop_size = zoom_window_size // zoom_level  # Size to crop from original image
            
            # Calculate crop bounds (centered on mouse position)
            half_crop = crop_size // 2
            left = max(0, img_mouse_x - half_crop)
            top = max(0, img_mouse_y - half_crop)
            right = min(pil_image.width, img_mouse_x + half_crop)
            bottom = min(pil_image.height, img_mouse_y + half_crop)
            
            # Crop the area around the mouse
            crop_area = pil_image.crop((left, top, right, bottom))
            
            # Resize to magnified size
            magnified_width = (right - left) * zoom_level
            magnified_height = (bottom - top) * zoom_level
            magnified_image = crop_area.resize((magnified_width, magnified_height), Image.LANCZOS)
            
            # Create zoom window (always create fresh since we destroy on leave)
            if not self.zoom_window:
                self.zoom_window = tk.Toplevel(self.root)
                self.zoom_window.overrideredirect(True)  # Remove window decorations
                self.zoom_window.attributes('-topmost', True)  # Keep on top
                
                # Create label for magnified image with no border
                self.zoom_label = tk.Label(self.zoom_window, bd=0, highlightthickness=0)
                self.zoom_label.pack()
            
            # Convert PIL image to PhotoImage
            from PIL import ImageTk
            photo = ImageTk.PhotoImage(magnified_image)
            self.zoom_label.config(image=photo, width=zoom_window_size, height=zoom_window_size)
            self.zoom_label.image = photo  # Keep a reference
            
            # Position window at bottom-right corner of the image
            root_x = self.root.winfo_rootx()
            root_y = self.root.winfo_rooty()
            
            # Get the image label position relative to root window
            label_x = self.image_label.winfo_x()
            label_y = self.image_label.winfo_y()
            
            # Find parent frames to get absolute position
            parent = self.image_label.master
            while parent != self.root:
                label_x += parent.winfo_x()
                label_y += parent.winfo_y()
                parent = parent.master
            
            # Calculate bottom-right corner of the actual displayed image
            window_x = root_x + label_x + img_x + display_width - zoom_window_size - 10
            window_y = root_y + label_y + img_y + display_height - zoom_window_size - 10
            
            # Ensure window stays on screen
            screen_width = self.root.winfo_screenwidth()
            screen_height = self.root.winfo_screenheight()
            
            if window_x + zoom_window_size > screen_width:
                window_x = screen_width - zoom_window_size - 10
            if window_x < 0:
                window_x = 10
            if window_y + zoom_window_size > screen_height:
                window_y = screen_height - zoom_window_size - 10
            if window_y < 0:
                window_y = 10
                    
            self.zoom_window.geometry(f"{zoom_window_size}x{zoom_window_size}+{window_x}+{window_y}")
            
        except Exception as e:
            print(f"Error showing zoom window: {e}")
    
    def toggle_gallery_view(self):
        """Toggle between single image view and gallery grid view"""
        if not self.current_images:
            return
            
        self.gallery_mode = not self.gallery_mode
        
        if self.gallery_mode:
            self.show_gallery_view()
        else:
            self.show_single_view()
    
    def show_gallery_view(self):
        """Show gallery grid view and hide left/middle columns"""
        # Hide left and middle frames
        self.left_frame.pack_forget()
        self.middle_frame.pack_forget()
        
        # Update button text
        self.gallery_button.config(text="single")
        
        # Create gallery frame if it doesn't exist
        if not self.gallery_frame:
            self.create_gallery_frame()
        
        # Show gallery frame
        self.gallery_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))
        
        # Update gallery title with designer name
        if self.gallery_title_label and self.current_designer_name:
            self.gallery_title_label.config(text=self.current_designer_name)
        
        # Populate gallery with images
        self.populate_gallery()
    
    def show_single_view(self):
        """Show single image view and restore left/middle columns"""
        # Hide gallery frame
        if self.gallery_frame:
            self.gallery_frame.pack_forget()
        
        # Unbind global scroll events
        if hasattr(self, 'gallery_scroll_bindings'):
            for binding in self.gallery_scroll_bindings:
                try:
                    self.root.unbind_all(binding)
                except:
                    pass
        
        # Show left frame and other columns if activated
        self.left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 5))
        if self.column2_activated:
            self.middle_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(5, 5))
        if self.column3_activated:
            self.right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))
        
        # Update button text
        self.gallery_button.config(text="gallery")
    
    def create_gallery_frame(self):
        """Create the gallery frame with scrollable grid"""
        self.gallery_frame = ttk.Frame(self.main_container, width=700)
        self.gallery_frame.pack_propagate(False)
        
        # Title for gallery (will be updated dynamically)
        self.gallery_title_label = ttk.Label(self.gallery_frame, text="", 
                                            font=('Arial', 12, 'bold'))
        self.gallery_title_label.pack(pady=(0, 10))
        
        # Create canvas and scrollbar for scrollable grid
        canvas_frame = ttk.Frame(self.gallery_frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        
        self.gallery_canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        self.gallery_scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, 
                                              command=self.gallery_canvas.yview)
        self.gallery_canvas.config(yscrollcommand=self.gallery_scrollbar.set)
        
        self.gallery_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.gallery_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Inner frame for grid content
        self.gallery_inner_frame = ttk.Frame(self.gallery_canvas)
        self.gallery_canvas.create_window(0, 0, window=self.gallery_inner_frame, anchor='nw')
        
        # Bind canvas configuration
        self.gallery_inner_frame.bind('<Configure>', self.on_gallery_configure)
        self.gallery_canvas.bind('<Configure>', self.on_canvas_configure)
        
        # Bind mouse wheel scrolling for trackpad support
        # Use bind_all to capture scroll events globally when in gallery mode
        self.gallery_canvas.bind_all('<MouseWheel>', self.on_gallery_mousewheel)
        self.gallery_canvas.bind_all('<Button-4>', self.on_gallery_mousewheel)  
        self.gallery_canvas.bind_all('<Button-5>', self.on_gallery_mousewheel)
        
        # Also bind directly to canvas and frame for better coverage
        self.gallery_canvas.bind('<MouseWheel>', self.on_gallery_mousewheel)
        self.gallery_canvas.bind('<Button-4>', self.on_gallery_mousewheel)
        self.gallery_canvas.bind('<Button-5>', self.on_gallery_mousewheel)
        
        canvas_frame.bind('<MouseWheel>', self.on_gallery_mousewheel)
        canvas_frame.bind('<Button-4>', self.on_gallery_mousewheel)
        canvas_frame.bind('<Button-5>', self.on_gallery_mousewheel)
        
        # Enable focus for the canvas
        self.gallery_canvas.focus_set()
        
        # Store reference to unbind later
        self.gallery_scroll_bindings = [
            '<MouseWheel>',
            '<Button-4>',
            '<Button-5>'
        ]
    
    def on_gallery_configure(self, event):
        """Update scroll region when gallery content changes"""
        self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox('all'))
    
    def on_canvas_configure(self, event):
        """Update inner frame width when canvas is resized"""
        canvas_width = event.width
        self.gallery_canvas.itemconfig(self.gallery_canvas.find_all()[0], width=canvas_width)
    
    def bind_mousewheel_to_widget(self, widget):
        """Bind mouse wheel events to a widget for scrolling"""
        # Windows and MacOS
        widget.bind('<MouseWheel>', self.on_gallery_mousewheel)
        # Linux
        widget.bind('<Button-4>', self.on_gallery_mousewheel)
        widget.bind('<Button-5>', self.on_gallery_mousewheel)
        # Additional trackpad support
        widget.bind('<Shift-MouseWheel>', self.on_gallery_mousewheel)
    
    def on_gallery_mousewheel(self, event):
        """Handle mouse wheel scrolling in gallery view"""
        # Only scroll if we're in gallery mode and canvas exists
        if not self.gallery_mode or not self.gallery_canvas:
            return
            
        print(f"Gallery scroll event: delta={getattr(event, 'delta', None)}, num={getattr(event, 'num', None)}")
            
        # Determine scroll direction and amount
        delta = 0
        if hasattr(event, 'num') and event.num in (4, 5):
            # Linux scroll wheel
            if event.num == 4:
                delta = -1  # Scroll up
            elif event.num == 5:
                delta = 1   # Scroll down
        elif hasattr(event, 'delta') and event.delta != 0:
            # Windows/Mac - delta is positive for up, negative for down
            if event.delta > 0:
                delta = -1  # Scroll up
            elif event.delta < 0:
                delta = 1   # Scroll down
        
        if delta != 0:
            print(f"Scrolling gallery with delta: {delta}")
            # Scroll the canvas
            self.gallery_canvas.yview_scroll(delta, "units")
            return "break"  # Prevent event propagation
    
    def populate_gallery(self):
        """Populate gallery with image thumbnails in 4-column grid"""
        if not self.current_images:
            return
        
        # Clear existing gallery buttons
        for widget in self.gallery_inner_frame.winfo_children():
            widget.destroy()
        self.gallery_image_buttons = []
        
        # Fixed container dimensions
        container_width = 160
        container_height = 200  # Extra height for label
        normal_max_size = 120
        highlighted_max_size = 150
        padding = 10
        
        # Create grid of image thumbnails
        for i, image_path in enumerate(self.current_images):
            row = i // 4  # 4 columns instead of 5
            col = i % 4
            
            # Determine if this is the current image
            is_current = (i == self.current_image_index)
            max_size = highlighted_max_size if is_current else normal_max_size
            
            try:
                # Load and resize image for thumbnail
                from PIL import Image, ImageTk
                from pathlib import Path
                
                if not Path(image_path).exists():
                    continue
                    
                pil_image = Image.open(image_path)
                
                # Create thumbnail preserving aspect ratio
                thumb_image = self.create_aspect_ratio_thumbnail(pil_image, max_size)
                photo = ImageTk.PhotoImage(thumb_image)
                
                # Create fixed-size container frame
                container_frame = ttk.Frame(self.gallery_inner_frame, 
                                          width=container_width, 
                                          height=container_height)
                container_frame.grid(row=row, column=col, padx=padding, pady=padding)
                container_frame.pack_propagate(False)  # Keep fixed size
                container_frame.grid_propagate(False)   # Keep fixed size
                
                # Create inner frame for centering
                inner_frame = ttk.Frame(container_frame)
                inner_frame.place(relx=0.5, rely=0.4, anchor='center')  # Center in container
                
                # Create button for image
                image_btn = tk.Button(inner_frame, image=photo, 
                                    command=lambda idx=i: self.gallery_image_click(idx),
                                    bd=3 if is_current else 1,
                                    relief='solid' if is_current else 'raised',
                                    bg='lightblue' if is_current else 'white',
                                    highlightthickness=0)
                image_btn.pack()
                image_btn.image = photo  # Keep reference
                
                # Add hover effects (only for non-current images)
                if not is_current:
                    image_btn.bind('<Enter>', lambda e, idx=i: self.on_gallery_hover_enter(idx))
                    image_btn.bind('<Leave>', lambda e, idx=i: self.on_gallery_hover_leave(idx))
                
                
                # Add look number label at bottom of container
                filename = Path(image_path).name
                import re
                look_match = re.search(r'-(\d+)\.[^.]+$', filename)
                if look_match:
                    look_number = look_match.group(1)
                    label = ttk.Label(container_frame, text=f"Look {look_number}", 
                                    font=('Arial', 8), anchor='center')
                    label.place(relx=0.5, rely=0.85, anchor='center')  # Bottom center
                    
                
                self.gallery_image_buttons.append((image_btn, container_frame, inner_frame, i))
                
            except Exception as e:
                print(f"Error creating thumbnail for {image_path}: {e}")
        
        # Update scroll region
        self.gallery_inner_frame.update_idletasks()
        self.gallery_canvas.configure(scrollregion=self.gallery_canvas.bbox('all'))
    
    def create_aspect_ratio_thumbnail(self, pil_image, max_size):
        """Create a thumbnail preserving original aspect ratio"""
        width, height = pil_image.size
        
        # Calculate scale factor to fit within max_size
        scale = min(max_size / width, max_size / height)
        
        # Calculate new dimensions
        new_width = int(width * scale)
        new_height = int(height * scale)
        
        # Resize maintaining aspect ratio
        return pil_image.resize((new_width, new_height), Image.Resampling.LANCZOS)
    
    def gallery_image_click(self, index):
        """Handle clicking an image in gallery view"""
        if 0 <= index < len(self.current_images):
            old_index = self.current_image_index
            self.current_image_index = index
            
            # Update the display for single image view (even though hidden)
            self.display_current_image()
            
            # Update gallery highlighting
            self.update_gallery_highlighting(old_index, index)
    
    def update_gallery_highlighting(self, old_index, new_index):
        """Update the highlighting in gallery view"""
        if not self.gallery_mode or not self.gallery_image_buttons:
            return
            
        normal_max_size = 120
        highlighted_max_size = 150
        
        try:
            # Update old image (make smaller and re-add hover effects)
            if 0 <= old_index < len(self.gallery_image_buttons):
                old_btn, old_container, old_inner, _ = self.gallery_image_buttons[old_index]
                old_btn.config(bd=1, relief='raised', bg='white')
                
                # Recreate thumbnail at normal size
                old_image_path = self.current_images[old_index]
                from PIL import Image, ImageTk
                from pathlib import Path
                
                if Path(old_image_path).exists():
                    pil_image = Image.open(old_image_path)
                    thumb_image = self.create_aspect_ratio_thumbnail(pil_image, normal_max_size)
                    photo = ImageTk.PhotoImage(thumb_image)
                    old_btn.config(image=photo)
                    old_btn.image = photo
                    
                    # Re-add hover effects to the old image
                    old_btn.bind('<Enter>', lambda e, idx=old_index: self.on_gallery_hover_enter(idx))
                    old_btn.bind('<Leave>', lambda e, idx=old_index: self.on_gallery_hover_leave(idx))
            
            # Update new image (make bigger and remove hover effects)
            if 0 <= new_index < len(self.gallery_image_buttons):
                new_btn, new_container, new_inner, _ = self.gallery_image_buttons[new_index]
                new_btn.config(bd=3, relief='solid', bg='lightblue')
                
                # Remove hover effects from the selected image
                new_btn.unbind('<Enter>')
                new_btn.unbind('<Leave>')
                
                # Recreate thumbnail at highlighted size
                new_image_path = self.current_images[new_index]
                from PIL import Image, ImageTk
                from pathlib import Path
                
                if Path(new_image_path).exists():
                    pil_image = Image.open(new_image_path)
                    thumb_image = self.create_aspect_ratio_thumbnail(pil_image, highlighted_max_size)
                    photo = ImageTk.PhotoImage(thumb_image)
                    new_btn.config(image=photo)
                    new_btn.image = photo
                    
        except Exception as e:
            print(f"Error updating gallery highlighting: {e}")
    
    def on_gallery_hover_enter(self, index):
        """Handle mouse entering a gallery image (hover effect)"""
        if not self.gallery_mode or not self.gallery_image_buttons:
            return
            
        if 0 <= index < len(self.gallery_image_buttons):
            # Skip if this is the currently selected image
            if index == self.current_image_index:
                return
                
            try:
                btn, container, inner, _ = self.gallery_image_buttons[index]
                
                # Create enlarged thumbnail at highlighted size (same as selected)
                image_path = self.current_images[index]
                from PIL import Image, ImageTk
                from pathlib import Path
                
                if Path(image_path).exists():
                    pil_image = Image.open(image_path)
                    highlighted_max_size = 150  # Same size as selected image
                    thumb_image = self.create_aspect_ratio_thumbnail(pil_image, highlighted_max_size)
                    photo = ImageTk.PhotoImage(thumb_image)
                    btn.config(image=photo, bd=2, relief='raised', bg='lightgray')
                    btn.image = photo  # Keep reference
                    
            except Exception as e:
                print(f"Error in hover enter: {e}")
    
    def on_gallery_hover_leave(self, index):
        """Handle mouse leaving a gallery image (revert hover effect)"""
        if not self.gallery_mode or not self.gallery_image_buttons:
            return
            
        if 0 <= index < len(self.gallery_image_buttons):
            # Skip if this is the currently selected image
            if index == self.current_image_index:
                return
                
            try:
                btn, container, inner, _ = self.gallery_image_buttons[index]
                
                # Revert to normal size
                image_path = self.current_images[index]
                from PIL import Image, ImageTk
                from pathlib import Path
                
                if Path(image_path).exists():
                    pil_image = Image.open(image_path)
                    normal_max_size = 120  # Normal size
                    thumb_image = self.create_aspect_ratio_thumbnail(pil_image, normal_max_size)
                    photo = ImageTk.PhotoImage(thumb_image)
                    btn.config(image=photo, bd=1, relief='raised', bg='white')
                    btn.image = photo  # Keep reference
                    
            except Exception as e:
                print(f"Error in hover leave: {e}")
    
    def start_video_download(self, collection):
        """Start video download in background parallel to image download"""
        if not VIDEO_FEATURES_AVAILABLE or not self.video_search_engine:
            return
        
        collection_name = f"{collection['designer']} {collection.get('season', '')} {collection.get('year', '')}"
        
        # Store collection info for other uses
        if VIDEO_FEATURES_AVAILABLE:
            self.current_collection_info = {
                'name': collection_name,
                'url': collection['url'],
                'designer': collection['designer']
            }
        
        print(f"\n🎬 STARTING VIDEO DOWNLOAD FOR: {collection_name}")
        
        def video_download_in_background():
            try:
                # Use the new Claude-powered search, verification, and download
                downloaded_path = self.video_search_engine.search_verify_and_download(collection_name)
                
                if downloaded_path:
                    print(f"✅ VIDEO READY: {downloaded_path}")
                    # Update UI in main thread
                    self.root.after(0, lambda: self.on_video_downloaded(downloaded_path))
                else:
                    print("❌ No video downloaded")
                    # Clear video in UI
                    self.root.after(0, lambda: self.on_video_downloaded(None))
                    
            except Exception as e:
                print(f"❌ Error downloading video: {e}")
                self.root.after(0, lambda: self.on_video_downloaded(None))
        
        # Start video download in background thread (parallel to images)
        threading.Thread(target=video_download_in_background, daemon=True).start()

    def clear_videos_folder(self):
        """Clear the videos folder when starting a new collection"""
        try:
            from pathlib import Path
            import shutil
            
            videos_dir = Path("videos")
            if videos_dir.exists():
                # Remove all files in videos directory
                for file_path in videos_dir.iterdir():
                    try:
                        if file_path.is_file():
                            file_path.unlink()
                            print(f"🗑️ Removed old video: {file_path.name}")
                    except Exception as e:
                        print(f"⚠️ Could not remove {file_path.name}: {e}")
                        
                print("🧹 Videos folder cleared for new collection")
            else:
                # Create videos directory if it doesn't exist
                videos_dir.mkdir(exist_ok=True)
                print("📁 Created videos folder")
                
        except Exception as e:
            print(f"❌ Error clearing videos folder: {e}")

    def on_video_downloaded(self, video_path):
        """Called when a video is successfully downloaded"""
        self.current_video_path = video_path
        
        if video_path and VIDEO_FEATURES_AVAILABLE and hasattr(self, 'video_button'):
            # Enable video button when video is available
            self.video_button.config(state=tk.NORMAL)
            print(f"🎬 Video button enabled for: {video_path}")
        else:
            # Disable video button when no video
            if VIDEO_FEATURES_AVAILABLE and hasattr(self, 'video_button'):
                self.video_button.config(state=tk.DISABLED)
    
    def toggle_video_player(self):
        """Toggle video player window"""
        if not self.current_video_path:
            print("❌ No video available")
            return
        
        if self.video_player_window and self.video_player_window.winfo_exists():
            # Close existing player
            self.video_player_window.destroy()
            self.video_player_window = None
        else:
            # Open new player
            self.create_video_player()
    
    def create_video_player(self):
        """Create a video player window"""
        if not self.current_video_path:
            return
        
        # Create new window
        self.video_player_window = tk.Toplevel(self.root)
        self.video_player_window.title("Fashion Show Video")
        self.video_player_window.geometry("800x600")
        
        # Make it stay on top but not always
        self.video_player_window.transient(self.root)
        
        try:
            import cv2
            
            # Create video player frame
            video_frame = ttk.Frame(self.video_player_window)
            video_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
            
            # Video display label
            self.video_label = tk.Label(video_frame, bg='black')
            self.video_label.pack(fill=tk.BOTH, expand=True)
            
            # Controls frame
            controls_frame = ttk.Frame(video_frame)
            controls_frame.pack(fill=tk.X, pady=(10, 0))
            
            # Play/Pause button
            self.play_button = ttk.Button(controls_frame, text="▶️", 
                                        command=self.toggle_playback)
            self.play_button.pack(side=tk.LEFT, padx=(0, 10))
            
            # Progress slider
            self.progress_var = tk.DoubleVar()
            self.progress_slider = ttk.Scale(controls_frame, from_=0, to=100, 
                                           variable=self.progress_var,
                                           command=self.on_slider_change,
                                           orient=tk.HORIZONTAL)
            self.progress_slider.pack(fill=tk.X, side=tk.LEFT, padx=(0, 10))
            
            # Time label
            self.time_label = tk.Label(controls_frame, text="00:00 / 00:00")
            self.time_label.pack(side=tk.RIGHT)
            
            # Initialize video
            self.init_video_player()
            
        except ImportError:
            # Fallback if OpenCV not available
            error_label = tk.Label(self.video_player_window, 
                                 text="Video player requires OpenCV\npip install opencv-python",
                                 font=("Arial", 14))
            error_label.pack(expand=True)
        
        # Handle window closing
        self.video_player_window.protocol("WM_DELETE_WINDOW", self.close_video_player)
    
    def init_video_player(self):
        """Initialize the video player with the current video"""
        try:
            import cv2
            from PIL import Image, ImageTk
            
            self.cap = cv2.VideoCapture(self.current_video_path)
            self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
            self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.duration = self.frame_count / self.fps
            
            self.current_frame = 0
            self.is_playing = False
            
            # Load first frame
            self.update_video_frame()
            
        except Exception as e:
            print(f"Error initializing video: {e}")
    
    def update_video_frame(self):
        """Update the video frame display"""
        try:
            import cv2
            from PIL import Image, ImageTk
            
            ret, frame = self.cap.read()
            if ret:
                # Convert BGR to RGB
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                
                # Resize frame to fit window
                height, width = frame_rgb.shape[:2]
                max_width, max_height = 760, 500
                
                if width > max_width or height > max_height:
                    ratio = min(max_width/width, max_height/height)
                    new_width = int(width * ratio)
                    new_height = int(height * ratio)
                    frame_rgb = cv2.resize(frame_rgb, (new_width, new_height))
                
                # Convert to PhotoImage
                img = Image.fromarray(frame_rgb)
                photo = ImageTk.PhotoImage(img)
                
                # Update label
                self.video_label.config(image=photo)
                self.video_label.image = photo  # Keep reference
                
                # Update progress
                progress = (self.current_frame / self.frame_count) * 100
                self.progress_var.set(progress)
                
                # Update time display
                current_time = self.current_frame / self.fps
                total_time = self.duration
                time_text = f"{self.format_time(current_time)} / {self.format_time(total_time)}"
                self.time_label.config(text=time_text)
                
                self.current_frame += 1
                
                # Continue playing if playing
                if self.is_playing and self.current_frame < self.frame_count:
                    self.video_player_window.after(int(1000/self.fps), self.update_video_frame)
                elif self.current_frame >= self.frame_count:
                    self.is_playing = False
                    self.play_button.config(text="▶️")
            
        except Exception as e:
            print(f"Error updating video frame: {e}")
    
    def toggle_playback(self):
        """Toggle play/pause"""
        if self.is_playing:
            self.is_playing = False
            self.play_button.config(text="▶️")
        else:
            self.is_playing = True
            self.play_button.config(text="⏸️")
            if self.current_frame < self.frame_count:
                self.update_video_frame()
    
    def on_slider_change(self, value):
        """Handle slider position change"""
        if not self.is_playing:  # Only allow seeking when paused
            try:
                import cv2
                progress = float(value)
                self.current_frame = int((progress / 100) * self.frame_count)
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, self.current_frame)
                self.update_video_frame()
            except Exception as e:
                print(f"Error seeking: {e}")
    
    def format_time(self, seconds):
        """Format time as MM:SS"""
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes:02d}:{seconds:02d}"
    
    def close_video_player(self):
        """Close video player and cleanup"""
        if hasattr(self, 'cap'):
            self.cap.release()
        if self.video_player_window:
            self.video_player_window.destroy()
            self.video_player_window = None
    
def main():
    """
    Main entry point for the Fashion Archive System
    """
    try:
        root = tk.Tk()
        app = FashionScraper(root)
        
        # Center window on screen
        root.update_idletasks()
        width = root.winfo_width()
        height = root.winfo_height()
        x = (root.winfo_screenwidth() // 2) - (width // 2)
        y = (root.winfo_screenheight() // 2) - (height // 2)
        root.geometry(f"{width}x{height}+{x}+{y}")
        
        # Set minimum window size
        root.minsize(800, 600)
        
        print("🎭 Fashion Archive System Started")
        print("📚 Preserving fashion history for future generations")
        if VIDEO_FEATURES_AVAILABLE:
            print("🤖 AI-powered video verification enabled")
        else:
            print("⚠️  Video features unavailable (missing dependencies)")
        print("=" * 50)
        
        root.mainloop()
        
    except Exception as e:
        print(f"❌ Error starting Fashion Archive System: {e}")
        import traceback
        traceback.print_exc()


def main():
    """
    Main entry point for the Fashion Archive System
    """
    try:
        root = tk.Tk()
        app = FashionScraper(root)
        
        # Center window on screen
        root.update_idletasks()
        width = root.winfo_width()
        height = root.winfo_height()
        x = (root.winfo_screenwidth() // 2) - (width // 2)
        y = (root.winfo_screenheight() // 2) - (height // 2)
        root.geometry(f"{width}x{height}+{x}+{y}")
        
        # Set minimum window size
        root.minsize(800, 600)
        
        print("🎭 Fashion Archive System Started")
        print("📚 Preserving fashion history for future generations")
        if VIDEO_FEATURES_AVAILABLE:
            print("🤖 AI-powered video verification enabled")
        else:
            print("⚠️  Video features unavailable (missing dependencies)")
        print("=" * 50)
        
        root.mainloop()
        
    except Exception as e:
        print(f"❌ Error starting Fashion Archive System: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()

