#!/usr/bin/env python3
"""
Video Player Widget for Fashion Shows
Provides video playback capabilities within the tkinter application.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
import threading
from typing import Optional, Callable
from dataclasses import dataclass
import subprocess
import sys
import platform


@dataclass
class VideoPlayerConfig:
    """Configuration for video player"""
    width: int = 400
    height: int = 300
    auto_play: bool = False
    show_controls: bool = True
    volume: float = 0.5


class VideoPlayerWidget:
    """
    Video player widget for tkinter applications.
    Since tkinter doesn't have native video support, this provides multiple playback options.
    """
    
    def __init__(self, parent_frame, config: VideoPlayerConfig = None):
        self.parent_frame = parent_frame
        self.config = config or VideoPlayerConfig()
        
        self.current_video_url = None
        self.current_video_title = None
        self.is_playing = False
        
        # Callbacks
        self.on_video_start: Optional[Callable] = None
        self.on_video_stop: Optional[Callable] = None
        
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the video player interface"""
        # Main container
        self.main_frame = ttk.Frame(self.parent_frame)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # Video info frame
        self.info_frame = ttk.Frame(self.main_frame)
        self.info_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.video_title_label = ttk.Label(
            self.info_frame, 
            text="No video loaded", 
            font=('Arial', 10, 'bold'),
            wraplength=self.config.width - 20
        )
        self.video_title_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        # Video display area (placeholder for now)
        self.video_frame = ttk.Frame(
            self.main_frame, 
            width=self.config.width, 
            height=self.config.height,
            relief='sunken',
            borderwidth=2
        )
        self.video_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        self.video_frame.pack_propagate(False)
        
        # Placeholder content
        self.placeholder_label = ttk.Label(
            self.video_frame,
            text="🎥\nNo video loaded\n\nVideo will open in browser",
            justify=tk.CENTER,
            font=('Arial', 12)
        )
        self.placeholder_label.place(relx=0.5, rely=0.5, anchor='center')
        
        # Controls frame
        self.controls_frame = ttk.Frame(self.main_frame)
        self.controls_frame.pack(fill=tk.X)
        
        # Play button
        self.play_button = ttk.Button(
            self.controls_frame,
            text="▶ Play in Browser",
            command=self.toggle_play,
            state=tk.DISABLED
        )
        self.play_button.pack(side=tk.LEFT, padx=(0, 10))
        
        # Open in browser button
        self.browser_button = ttk.Button(
            self.controls_frame,
            text="🌐 Open in Browser",
            command=self.open_in_browser,
            state=tk.DISABLED
        )
        self.browser_button.pack(side=tk.LEFT, padx=(0, 10))
        
        # Video info button
        self.info_button = ttk.Button(
            self.controls_frame,
            text="ℹ Info",
            command=self.show_video_info,
            state=tk.DISABLED
        )
        self.info_button.pack(side=tk.LEFT)
        
        # Status label
        self.status_label = ttk.Label(
            self.controls_frame,
            text="Ready",
            font=('Arial', 9)
        )
        self.status_label.pack(side=tk.RIGHT)
    
    def load_video(self, video_url: str, video_title: str = ""):
        """Load a video for playback"""
        self.current_video_url = video_url
        self.current_video_title = video_title or "Fashion Show Video"
        
        # Update UI
        self.video_title_label.config(text=self.current_video_title)
        self.placeholder_label.config(
            text=f"🎥\n{self.current_video_title[:50]}{'...' if len(self.current_video_title) > 50 else ''}\n\nReady to play"
        )
        
        # Enable controls
        self.play_button.config(state=tk.NORMAL)
        self.browser_button.config(state=tk.NORMAL)
        self.info_button.config(state=tk.NORMAL)
        
        self.status_label.config(text="Video loaded")
    
    def toggle_play(self):
        """Toggle video playback (opens in browser for now)"""
        if not self.current_video_url:
            return
        
        if not self.is_playing:
            self.play_video()
        else:
            self.stop_video()
    
    def play_video(self):
        """Start video playback"""
        if not self.current_video_url:
            messagebox.showwarning("No Video", "No video loaded to play")
            return
        
        try:
            # For now, open in browser
            # In the future, this could use embedded player
            webbrowser.open(self.current_video_url)
            
            self.is_playing = True
            self.play_button.config(text="⏸ Playing in Browser")
            self.status_label.config(text="Playing in browser")
            self.placeholder_label.config(
                text=f"🎥\n{self.current_video_title[:50]}{'...' if len(self.current_video_title) > 50 else ''}\n\nPlaying in browser..."
            )
            
            if self.on_video_start:
                self.on_video_start()
            
        except Exception as e:
            messagebox.showerror("Playback Error", f"Could not play video: {str(e)}")
    
    def stop_video(self):
        """Stop video playback"""
        self.is_playing = False
        self.play_button.config(text="▶ Play in Browser")
        self.status_label.config(text="Stopped")
        
        if self.current_video_title:
            self.placeholder_label.config(
                text=f"🎥\n{self.current_video_title[:50]}{'...' if len(self.current_video_title) > 50 else ''}\n\nReady to play"
            )
        
        if self.on_video_stop:
            self.on_video_stop()
    
    def open_in_browser(self):
        """Open video in external browser"""
        if self.current_video_url:
            webbrowser.open(self.current_video_url)
            self.status_label.config(text="Opened in browser")
    
    def show_video_info(self):
        """Show video information dialog"""
        if not self.current_video_url:
            return
        
        info_text = f"Title: {self.current_video_title}\n\nURL: {self.current_video_url}\n\nStatus: {'Playing' if self.is_playing else 'Ready'}"
        
        messagebox.showinfo("Video Information", info_text)
    
    def clear_video(self):
        """Clear current video"""
        self.current_video_url = None
        self.current_video_title = None
        self.is_playing = False
        
        # Reset UI
        self.video_title_label.config(text="No video loaded")
        self.placeholder_label.config(
            text="🎥\nNo video loaded\n\nVideo will open in browser"
        )
        self.play_button.config(text="▶ Play in Browser", state=tk.DISABLED)
        self.browser_button.config(state=tk.DISABLED)
        self.info_button.config(state=tk.DISABLED)
        self.status_label.config(text="Ready")
    
    def set_callbacks(self, on_start: Callable = None, on_stop: Callable = None):
        """Set callback functions for video events"""
        self.on_video_start = on_start
        self.on_video_stop = on_stop


class EnhancedVideoPlayer(VideoPlayerWidget):
    """
    Enhanced video player with additional features like embedded preview,
    video search integration, and better controls.
    """
    
    def __init__(self, parent_frame, config: VideoPlayerConfig = None):
        super().__init__(parent_frame, config)
        self.video_thumbnail = None
        self.setup_enhanced_features()
    
    def setup_enhanced_features(self):
        """Add enhanced features to the video player"""
        # Add thumbnail display capability
        self.thumbnail_label = ttk.Label(self.video_frame)
        self.thumbnail_label.place(relx=0.5, rely=0.3, anchor='center')
        
        # Enhanced controls
        self.volume_frame = ttk.Frame(self.controls_frame)
        self.volume_frame.pack(side=tk.RIGHT, padx=(10, 0))
        
        ttk.Label(self.volume_frame, text="Vol:").pack(side=tk.LEFT)
        self.volume_var = tk.DoubleVar(value=self.config.volume * 100)
        self.volume_scale = ttk.Scale(
            self.volume_frame,
            from_=0, to=100,
            length=80,
            variable=self.volume_var,
            orient=tk.HORIZONTAL
        )
        self.volume_scale.pack(side=tk.LEFT, padx=(5, 0))
    
    def load_video_with_thumbnail(self, video_url: str, video_title: str = "", thumbnail_url: str = ""):
        """Load video with thumbnail preview"""
        self.load_video(video_url, video_title)
        
        if thumbnail_url:
            self.load_thumbnail(thumbnail_url)
    
    def load_thumbnail(self, thumbnail_url: str):
        """Load and display video thumbnail"""
        def fetch_thumbnail():
            try:
                import requests
                from PIL import Image, ImageTk
                import io
                
                response = requests.get(thumbnail_url, timeout=10)
                response.raise_for_status()
                
                # Load and resize thumbnail
                image = Image.open(io.BytesIO(response.content))
                image = image.resize((200, 150), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
                
                # Update UI in main thread
                self.parent_frame.after(0, lambda: self.display_thumbnail(photo))
                
            except Exception as e:
                print(f"Error loading thumbnail: {e}")
        
        # Load thumbnail in background
        threading.Thread(target=fetch_thumbnail, daemon=True).start()
    
    def display_thumbnail(self, photo):
        """Display the loaded thumbnail"""
        self.thumbnail_label.config(image=photo)
        self.thumbnail_label.image = photo  # Keep reference
        self.placeholder_label.place_forget()  # Hide placeholder


# Test the video player
if __name__ == "__main__":
    def test_video_player():
        root = tk.Tk()
        root.title("Video Player Test")
        root.geometry("600x500")
        
        # Create video player
        player = EnhancedVideoPlayer(root)
        
        # Test with a sample video
        def load_test_video():
            player.load_video_with_thumbnail(
                "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "Sample Fashion Show Video",
                "https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg"
            )
        
        # Add test button
        test_button = ttk.Button(root, text="Load Test Video", command=load_test_video)
        test_button.pack(pady=10)
        
        root.mainloop()
    
    test_video_player()