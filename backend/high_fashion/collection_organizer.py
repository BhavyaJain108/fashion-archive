#!/usr/bin/env python3
"""
Fashion Collection Organizer
Analyzes folders of downloaded images to identify the main collection,
removes non-belonging images, and renames the folder accordingly.
"""

import os
import re
import shutil
import argparse
from pathlib import Path
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional, Set
import json


@dataclass
class CollectionInfo:
    """Information about a detected collection."""
    name: str
    season: str
    year: str
    designer: str
    confidence: float
    matching_files: List[str]
    total_files: int
    
    def __str__(self):
        return f"{self.designer} {self.season} {self.year} (confidence: {self.confidence:.2f})"


class FilenameAnalyzer:
    """Analyzes filenames to extract collection information."""
    
    def __init__(self):
        self.season_patterns = {
            'spring': r'spring|ss|spring-summer',
            'summer': r'summer',
            'fall': r'fall|autumn|fw|fall-winter',
            'winter': r'winter',
            'resort': r'resort|pre-fall|cruise',
            'pre-spring': r'pre-spring',
            'couture': r'couture|haute-couture'
        }
        
        self.year_pattern = r'20\d{2}|19\d{2}'
        self.designer_stopwords = {'menswear', 'womenswear', 'collection', 'show', 'runway', 'paris', 'milan', 'london', 'newyork'}
    
    def extract_components(self, filename: str) -> Dict[str, str]:
        """Extract designer, season, year from filename."""
        # Clean filename
        name = Path(filename).stem.lower()
        name = re.sub(r'^\d{3}_', '', name)  # Remove index prefix like "001_"
        name = re.sub(r'[_-]+', ' ', name)   # Replace separators with spaces
        
        components = {
            'designer': '',
            'season': '',
            'year': '',
            'original': filename
        }
        
        # Extract year
        year_match = re.search(self.year_pattern, name)
        if year_match:
            components['year'] = year_match.group()
        
        # Extract season
        for season, pattern in self.season_patterns.items():
            if re.search(pattern, name, re.IGNORECASE):
                components['season'] = season
                break
        
        # Extract designer name (remaining significant words)
        words = name.split()
        designer_words = []
        for word in words:
            # Skip common words, years, and seasons
            if (len(word) > 2 and 
                word not in self.designer_stopwords and
                not re.match(self.year_pattern, word) and
                not any(re.search(pattern, word) for pattern in self.season_patterns.values())):
                designer_words.append(word)
        
        if designer_words:
            components['designer'] = ' '.join(designer_words[:2])  # Take first 2 significant words
        
        return components
    
    def calculate_similarity(self, comp1: Dict[str, str], comp2: Dict[str, str]) -> float:
        """Calculate similarity score between two filename components."""
        score = 0.0
        
        # Designer match (strict - must be exact match)
        if comp1['designer'] and comp2['designer']:
            if comp1['designer'] == comp2['designer']:
                score += 4.0
            else:
                # Different designers should definitely not be grouped
                score -= 3.0
        
        # Season match (must match for same collection)
        if comp1['season'] and comp2['season']:
            if comp1['season'] == comp2['season']:
                score += 3.0
            else:
                # Different seasons should not be grouped together
                score -= 3.0
        
        # Year match (must match for same collection)  
        if comp1['year'] and comp2['year']:
            if comp1['year'] == comp2['year']:
                score += 3.0
            else:
                # Different years should not be grouped together
                score -= 3.0
        
        return score


class CollectionOrganizer:
    """Main class for organizing fashion collection images."""
    
    def __init__(self, folder_path: str, min_collection_size: int = 5, confidence_threshold: float = 0.6):
        self.folder_path = Path(folder_path)
        self.min_collection_size = min_collection_size  
        self.confidence_threshold = confidence_threshold
        self.analyzer = FilenameAnalyzer()
        
        # More aggressive settings for mixed collection detection
        self.strict_designer_matching = True
    
    def remove_mixed_designers(self, files: List[str]) -> List[str]:
        """Remove files that are clearly from different designers/collections."""
        designer_counts = defaultdict(list)
        
        # Group files by designer name extracted from filename
        for file in files:
            designer = self.extract_designer_from_filename(file)
            if designer:
                designer_counts[designer].append(file)
        
        if len(designer_counts) <= 1:
            return files  # Only one designer, nothing to remove
        
        # Find the main designer (most files)
        main_designer = max(designer_counts.keys(), key=lambda d: len(designer_counts[d]))
        main_files = designer_counts[main_designer]
        
        # Remove files from other designers
        removed_files = []
        for designer, designer_files in designer_counts.items():
            if designer != main_designer:
                removed_files.extend(designer_files)
        
        if removed_files:
            print(f"Removing {len(removed_files)} files from other designers:")
            for file in removed_files:
                print(f"  - {file}")
            
            # Move removed files to removed_files folder
            if not dry_run:
                removed_folder = self.folder_path / 'removed_files'
                removed_folder.mkdir(exist_ok=True)
                
                for file in removed_files:
                    src = self.folder_path / file
                    dst = removed_folder / file
                    if src.exists():
                        import shutil
                        shutil.move(str(src), str(dst))
        
        return main_files
    
    def extract_designer_from_filename(self, filename: str) -> Optional[str]:
        """Extract designer name from filename."""
        # Remove file extension and index prefix
        name = filename.lower()
        name = re.sub(r'^\d+_', '', name)  # Remove index prefix like "040_"
        name = re.sub(r'\.(jpg|jpeg|png|gif|webp|bmp)$', '', name)  # Remove extension
        
        # Split by common separators
        parts = re.split(r'[-_\s]+', name)
        
        # Look for designer name (usually first meaningful part)
        designer_parts = []
        for part in parts:
            if part in ['menswear', 'womenswear', 'spring', 'summer', 'fall', 'winter', 
                       'ready', 'wear', 'couture', 'fashion', 'week', 'runway', 
                       'paris', 'milan', 'london', 'newyork', '2024', '2025', '2026', '001', '002']:
                break
            if len(part) > 1:  # Skip single character parts
                designer_parts.append(part)
        
        return '-'.join(designer_parts) if designer_parts else None
    
    def organize_folder_with_url_info(self, url_collection_name: str, dry_run: bool = False) -> Dict:
        """Organize folder using second image as reference pattern."""
        files = self.scan_folder()
        
        if not files:
            return {'error': 'No image files found in folder'}
        
        print(f"Organizing {len(files)} files using longest consecutive series")
        
        # Find the longest consecutive series of images with the same pattern
        import re
        from collections import defaultdict
        
        # Group files by their core pattern (excluding look numbers)
        pattern_groups = defaultdict(list)
        
        for file in files:
            # Extract core pattern by removing numbers from end
            pattern_match = re.match(r'^(.+?)-\d+\.[^.]+$', file)
            if pattern_match:
                core_pattern = pattern_match.group(1)
                pattern_groups[core_pattern].append(file)
            else:
                # Files that don't match the pattern go to a generic group
                pattern_groups['other'].append(file)
        
        print(f"Found {len(pattern_groups)} different patterns:")
        for pattern, pattern_files in pattern_groups.items():
            print(f"  '{pattern}': {len(pattern_files)} files")
        
        # Find the group with the most files (longest consecutive series)
        if pattern_groups:
            largest_pattern = max(pattern_groups.keys(), key=lambda k: len(pattern_groups[k]))
            matching_files = pattern_groups[largest_pattern]
            
            # Sort matching files by look number
            def extract_look_number(filename):
                look_match = re.search(r'-(\d+)\.[^.]+$', filename)
                return int(look_match.group(1)) if look_match else 0
            
            matching_files.sort(key=extract_look_number)
            print(f"Sorted {len(matching_files)} files by look number")
            
            # All other files are non-matching
            non_matching_files = []
            for pattern, pattern_files in pattern_groups.items():
                if pattern != largest_pattern:
                    non_matching_files.extend(pattern_files)
            
            print(f"Keeping largest group '{largest_pattern}' with {len(matching_files)} files")
            print(f"Removing {len(non_matching_files)} files from other patterns")
        else:
            print("No patterns found, keeping all files")
            matching_files = files
            non_matching_files = []
        
        # Move non-matching files to removed_files folder
        if non_matching_files and not dry_run:
            removed_folder = self.folder_path / 'removed_files'
            removed_folder.mkdir(exist_ok=True)
            
            print("Moving non-matching files to removed_files:")
            for file in non_matching_files:
                src = self.folder_path / file
                dst = removed_folder / file
                if src.exists():
                    shutil.move(str(src), str(dst))
                    print(f"  - {file}")
        
        return {
            'url_collection': url_collection_name,
            'largest_pattern': largest_pattern if pattern_groups else None,
            'total_files': len(files),
            'keeping_files': len(matching_files),
            'removing_files': len(non_matching_files),
            'removed_files': non_matching_files,
            'dry_run': dry_run
        }
    
    def parse_url_collection_name(self, url_name: str) -> Dict[str, str]:
        """Parse collection info from URL collection name."""
        parts = url_name.lower().split('-')
        
        info = {
            'designer': '',
            'season': '',
            'year': '',
            'city': ''
        }
        
        designer_parts = []
        i = 0
        
        # Extract designer name (everything before season keywords)
        while i < len(parts):
            part = parts[i]
            if part in ['menswear', 'womenswear', 'ready', 'spring', 'summer', 'fall', 'winter', 'couture']:
                break
            designer_parts.append(part)
            i += 1
        
        info['designer'] = '-'.join(designer_parts)
        
        # Extract season and year
        remaining_parts = parts[i:]
        for part in remaining_parts:
            if part in ['spring', 'summer', 'fall', 'winter', 'couture']:
                if info['season']:
                    info['season'] += f"-{part}"
                else:
                    info['season'] = part
            elif part.isdigit() and len(part) == 4:
                info['year'] = part
            elif part in ['paris', 'milan', 'london', 'newyork']:
                info['city'] = part
        
        return info
    
    def file_matches_url_collection(self, filename: str, expected_info: Dict[str, str]) -> bool:
        """Check if a file matches the expected collection from URL."""
        filename_lower = filename.lower()
        
        # Check designer match (must match)
        if expected_info['designer']:
            designer_clean = expected_info['designer'].replace('-', '')
            if designer_clean not in filename_lower.replace('-', '').replace('_', ''):
                return False
        
        # Check season match (must match if present)
        if expected_info['season']:
            season_parts = expected_info['season'].split('-')
            for season_part in season_parts:
                if season_part not in filename_lower:
                    return False
        
        # Check year match (must match if present)
        if expected_info['year']:
            if expected_info['year'] not in filename_lower:
                return False
        
        return True
        
    def scan_folder(self) -> List[str]:
        """Scan folder for image files."""
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        image_files = []
        
        for file in self.folder_path.iterdir():
            if file.is_file() and file.suffix.lower() in image_extensions:
                image_files.append(file.name)
        
        return sorted(image_files)
    
    def group_by_similarity(self, files: List[str]) -> List[List[str]]:
        """Group files by similarity of their extracted components."""
        components = [self.analyzer.extract_components(f) for f in files]
        groups = []
        used_indices = set()
        
        for i, comp1 in enumerate(components):
            if i in used_indices:
                continue
                
            group = [files[i]]
            used_indices.add(i)
            
            for j, comp2 in enumerate(components):
                if j in used_indices or i == j:
                    continue
                
                similarity = self.analyzer.calculate_similarity(comp1, comp2)
                if similarity >= 2.0:  # Threshold for grouping
                    group.append(files[j])
                    used_indices.add(j)
            
            groups.append(group)
        
        return groups
    
    def analyze_collections(self, files: List[str]) -> List[CollectionInfo]:
        """Analyze files to identify possible collections."""
        groups = self.group_by_similarity(files)
        collections = []
        
        for group in groups:
            if len(group) < self.min_collection_size:
                continue
            
            # Analyze the group to extract collection info
            components = [self.analyzer.extract_components(f) for f in group]
            
            # Find most common values
            designers = [c['designer'] for c in components if c['designer']]
            seasons = [c['season'] for c in components if c['season']]
            years = [c['year'] for c in components if c['year']]
            
            if not designers:
                continue
            
            designer = Counter(designers).most_common(1)[0][0]
            season = Counter(seasons).most_common(1)[0][0] if seasons else ''
            year = Counter(years).most_common(1)[0][0] if years else ''
            
            # Calculate confidence based on consistency
            designer_consistency = designers.count(designer) / len(designers) if designers else 0
            season_consistency = seasons.count(season) / len(seasons) if seasons else 0.5
            year_consistency = years.count(year) / len(years) if years else 0.5
            
            confidence = (designer_consistency * 0.6 + season_consistency * 0.3 + year_consistency * 0.1)
            
            collection = CollectionInfo(
                name=f"{designer}_{season}_{year}".strip('_'),
                season=season,
                year=year,
                designer=designer,
                confidence=confidence,
                matching_files=group,
                total_files=len(files)
            )
            
            collections.append(collection)
        
        # Sort by size first (larger collections preferred), then confidence
        return sorted(collections, key=lambda x: (len(x.matching_files), x.confidence), reverse=True)
    
    def identify_main_collection(self, files: List[str]) -> Optional[CollectionInfo]:
        """Identify the main collection from the files."""
        collections = self.analyze_collections(files)
        
        if not collections:
            return None
        
        main_collection = collections[0]
        
        # Check if the main collection meets our criteria
        if (main_collection.confidence >= self.confidence_threshold and 
            len(main_collection.matching_files) >= self.min_collection_size):
            return main_collection
        
        return None
    
    def organize_folder(self, dry_run: bool = False) -> Dict:
        """Organize the folder by identifying main collection and removing outliers."""
        files = self.scan_folder()
        
        if not files:
            return {'error': 'No image files found in folder'}
        
        # First, detect and remove mixed designer files
        files = self.remove_mixed_designers(files)
        
        main_collection = self.identify_main_collection(files)
        
        if not main_collection:
            return {
                'error': 'Could not identify a main collection with sufficient confidence',
                'total_files': len(files),
                'min_collection_size': self.min_collection_size,
                'confidence_threshold': self.confidence_threshold
            }
        
        # Files to keep and remove
        keep_files = set(main_collection.matching_files)
        remove_files = [f for f in files if f not in keep_files]
        
        # Generate new folder name
        new_folder_name = self.generate_folder_name(main_collection)
        new_folder_path = self.folder_path.parent / new_folder_name
        
        result = {
            'main_collection': str(main_collection),
            'total_files': len(files),
            'keeping_files': len(keep_files),
            'removing_files': len(remove_files),
            'removed_files': remove_files,
            'old_folder': str(self.folder_path),
            'new_folder': str(new_folder_path),
            'dry_run': dry_run
        }
        
        if not dry_run:
            # Create removed_files folder if there are files to remove
            if remove_files:
                removed_folder = self.folder_path / 'removed_files'
                removed_folder.mkdir(exist_ok=True)
                
                for file in remove_files:
                    src = self.folder_path / file
                    dst = removed_folder / file
                    shutil.move(str(src), str(dst))
                    print(f"Moved to removed_files/: {file}")
            
            # Rename folder if new name is different
            if new_folder_name != self.folder_path.name and not new_folder_path.exists():
                self.folder_path.rename(new_folder_path)
                result['renamed'] = True
                print(f"Renamed folder: {self.folder_path.name} -> {new_folder_name}")
            else:
                result['renamed'] = False
        
        return result
    
    def generate_folder_name(self, collection: CollectionInfo) -> str:
        """Generate a clean folder name for the collection."""
        # Always return 'images' to prevent renaming (now in cache structure)
        return "images"
        
        # Original code commented out:
        # parts = []
        # 
        # if collection.designer:
        #     # Clean designer name
        #     designer = re.sub(r'[^\w\s-]', '', collection.designer)
        #     designer = re.sub(r'\s+', '_', designer.strip())
        #     parts.append(designer)
        # 
        # if collection.season:
        #     parts.append(collection.season)
        # 
        # if collection.year:
        #     parts.append(collection.year)
        # 
        # folder_name = '_'.join(parts)
        # 
        # # Clean up the folder name
        # folder_name = re.sub(r'[^\w\s_-]', '', folder_name)
        # folder_name = re.sub(r'[_\s-]+', '_', folder_name)
        # 
        # return folder_name.lower()
    
    def organize_folder_with_target_collection(self, target_info: Dict[str, str], dry_run: bool = False) -> Dict:
        """Organize folder using target collection info from URL."""
        files = self.scan_folder()
        
        if not files:
            return {'error': 'No image files found in folder'}
        
        # Filter files that match the target collection
        matching_files = []
        for file in files:
            components = self.analyzer.extract_components(file)
            if self._matches_target_collection(components, target_info):
                matching_files.append(file)
        
        if len(matching_files) < self.min_collection_size:
            return {
                'error': f'Only {len(matching_files)} files match target collection (need at least {self.min_collection_size})',
                'target_info': target_info,
                'total_files': len(files),
                'matching_files': len(matching_files)
            }
        
        # Files to keep and remove
        keep_files = set(matching_files)
        remove_files = [f for f in files if f not in keep_files]
        
        # Generate folder name from target info
        new_folder_name = self._generate_folder_name_from_target(target_info)
        new_folder_path = self.folder_path.parent / new_folder_name
        
        result = {
            'target_collection': target_info,
            'total_files': len(files),
            'keeping_files': len(keep_files),
            'removing_files': len(remove_files),
            'removed_files': remove_files,
            'old_folder': str(self.folder_path),
            'new_folder': str(new_folder_path),
            'dry_run': dry_run
        }
        
        if not dry_run:
            # Create removed_files folder if there are files to remove
            if remove_files:
                removed_folder = self.folder_path / 'removed_files'
                removed_folder.mkdir(exist_ok=True)
                
                for file in remove_files:
                    src = self.folder_path / file
                    dst = removed_folder / file
                    shutil.move(str(src), str(dst))
                    print(f"Moved to removed_files/: {file}")
            
            # Rename folder if new name is different
            if new_folder_name != self.folder_path.name and not new_folder_path.exists():
                self.folder_path.rename(new_folder_path)
                result['renamed'] = True
                print(f"Renamed folder: {self.folder_path.name} -> {new_folder_name}")
            else:
                result['renamed'] = False
        
        return result
    
    def _matches_target_collection(self, components: Dict[str, str], target_info: Dict[str, str]) -> bool:
        """Check if filename contains the target collection name."""
        collection_name = target_info.get('collection_name', '').lower()
        filename = components.get('original', '').lower()
        
        # Simple check: does the filename contain the collection name?
        return collection_name in filename if collection_name else False
    
    def _generate_folder_name_from_target(self, target_info: Dict[str, str]) -> str:
        """Generate folder name from target collection info."""
        collection_name = target_info.get('collection_name', '')
        
        # Clean up the collection name for folder use
        folder_name = collection_name.replace('-', '_')
        folder_name = re.sub(r'[^\w\s_-]', '', folder_name)
        folder_name = re.sub(r'[_\s-]+', '_', folder_name)
        
        return folder_name.lower()


def main():
    parser = argparse.ArgumentParser(description="Organize fashion collection images")
    parser.add_argument("folder", help="Path to folder containing images")
    parser.add_argument("--min-size", type=int, default=5, 
                       help="Minimum collection size (default: 5)")
    parser.add_argument("--confidence", type=float, default=0.6,
                       help="Minimum confidence threshold (default: 0.6)")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be done without making changes")
    parser.add_argument("--analyze-only", action="store_true",
                       help="Only analyze and show collections, don't organize")
    
    args = parser.parse_args()
    
    if not os.path.exists(args.folder):
        print(f"Error: Folder '{args.folder}' does not exist")
        return
    
    organizer = CollectionOrganizer(
        args.folder, 
        min_collection_size=args.min_size,
        confidence_threshold=args.confidence
    )
    
    if args.analyze_only:
        files = organizer.scan_folder()
        collections = organizer.analyze_collections(files)
        
        print(f"\nFound {len(files)} image files")
        print(f"Detected {len(collections)} possible collections:\n")
        
        for i, collection in enumerate(collections, 1):
            print(f"{i}. {collection}")
            print(f"   Files: {len(collection.matching_files)}")
            print(f"   Sample files: {', '.join(collection.matching_files[:3])}")
            if len(collection.matching_files) > 3:
                print(f"   ... and {len(collection.matching_files) - 3} more")
            print()
    else:
        result = organizer.organize_folder(dry_run=args.dry_run)
        
        if 'error' in result:
            print(f"Error: {result['error']}")
            if 'total_files' in result:
                print(f"Total files: {result['total_files']}")
                print(f"Try lowering --min-size (currently {result['min_collection_size']}) or --confidence (currently {result['confidence_threshold']:.2f})")
        else:
            print(f"Analysis complete!")
            print(f"Main collection: {result['main_collection']}")
            print(f"Total files: {result['total_files']}")
            print(f"Keeping: {result['keeping_files']} files")
            print(f"Removing: {result['removing_files']} files")
            
            if result['removing_files'] > 0:
                print(f"Removed files: {', '.join(result['removed_files'])}")
            
            if result['dry_run']:
                print(f"\nDRY RUN - No changes made")
                print(f"Would rename: {result['old_folder']} -> {result['new_folder']}")
            else:
                if result.get('renamed'):
                    print(f"Renamed folder to: {Path(result['new_folder']).name}")


if __name__ == "__main__":
    main()