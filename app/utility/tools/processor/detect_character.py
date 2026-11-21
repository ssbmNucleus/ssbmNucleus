#!/usr/bin/env python3
"""
Simple DAT file parser to detect Melee character and costume color
Based on HSDLib's symbol detection logic
"""

import struct
import os
import sys

class DATParser:
    def __init__(self, filepath):
        self.filepath = filepath
        self.data = None
        self.file_size = 0
        self.data_block_size = 0
        self.relocation_table_count = 0
        self.root_count = 0
        self.root_nodes = []
        self.string_table = b""
        
    def read_dat(self):
        """Read and parse a DAT file to extract character information"""
        with open(self.filepath, 'rb') as f:
            self.data = f.read()
            
        # DAT file header structure:
        # 0x00: File Size
        # 0x04: Data Block Size  
        # 0x08: Relocation Table Count
        # 0x0C: Root Node Count
        # 0x10: Reference Node Count
        # 0x14: Unknown
        # 0x18: Unknown
        # 0x1C: Unknown
        # 0x20: Start of data

        # Read header
        self.file_size = struct.unpack('>I', self.data[0x00:0x04])[0]
        self.data_block_size = struct.unpack('>I', self.data[0x04:0x08])[0]
        self.relocation_table_count = struct.unpack('>I', self.data[0x08:0x0C])[0]
        self.root_count = struct.unpack('>I', self.data[0x0C:0x10])[0]
        self.ref_count = struct.unpack('>I', self.data[0x10:0x14])[0]

        # Calculate offsets. The string table sits after BOTH the root and
        # reference node tables (8 bytes per entry each); ignoring the
        # reference nodes made every symbol read garbage on files with refs.
        data_start = 0x20
        relocation_table_start = data_start + self.data_block_size
        root_node_table_start = relocation_table_start + (self.relocation_table_count * 4)
        string_table_start = root_node_table_start + ((self.root_count + self.ref_count) * 8)
        
        # Read root nodes (each is 8 bytes: 4 bytes offset + 4 bytes string offset)
        for i in range(self.root_count):
            offset = root_node_table_start + (i * 8)
            data_offset = struct.unpack('>I', self.data[offset:offset+4])[0]
            string_offset = struct.unpack('>I', self.data[offset+4:offset+8])[0]
            
            # Read string from string table
            string_addr = string_table_start + string_offset
            string_end = self.data.find(b'\x00', string_addr)
            symbol_name = self.data[string_addr:string_end].decode('ascii', errors='ignore')
            
            self.root_nodes.append({
                'data_offset': data_offset,
                'symbol': symbol_name
            })
            
    def detect_character(self):
        """Detect character from root node symbols"""
        
        # Character mapping based on ftData symbols
        character_map = {
            'ftDataCaptain': 'C. Falcon',
            'ftDataDonkey': 'DK', 
            'ftDataFox': 'Fox',
            'ftDataGame': 'Mr. Game & Watch',
            'ftDataKirby': 'Kirby',
            'ftDataKoopa': 'Bowser',
            'ftDataGkoopa': 'Giga Bowser',
            'ftDataLink': 'Link',
            'ftDataLuigi': 'Luigi',
            'ftDataMario': 'Mario',
            'ftDataMars': 'Marth',
            'ftDataMewtwo': 'Mewtwo',
            'ftDataNess': 'Ness',
            'ftDataPeach': 'Peach',
            'ftDataPichu': 'Pichu',
            'ftDataPikachu': 'Pikachu',
            'ftDataPurin': 'Jigglypuff',
            'ftDataSamus': 'Samus',
            'ftDataSeak': 'Sheik',
            'ftDataYoshi': 'Yoshi',
            'ftDataZelda': 'Zelda',
            'ftDataPopo': 'Ice Climbers',
            'ftDataNana': 'Ice Climbers (Nana)',
            # The Boy/Girl fighters are the Male/Female WIREFRAMES (PlBo/PlGl),
            # not Young Link (PlCl = ftDataClink). Mapping them to Young Link
            # filed wireframe recolor packs under Young Link's skins.
            'ftDataBoy': 'Wireframe Male',
            'ftDataGirl': 'Wireframe Female',
            'ftDataClink': 'Young Link',
            'ftDataMasterhand': 'Master Hand',
            'ftDataCrazyhand': 'Crazy Hand',
            'ftDataSandbag': 'Sandbag',
            'ftDataGanon': 'Ganondorf',
            'ftDataEmblem': 'Roy',
            'ftDataFalco': 'Falco',
            'ftDataMarioD': 'Dr. Mario',
            'ftDataDrmario': 'Dr. Mario',
            # PlCo files (costume files)
            'PlyCaptain': 'C. Falcon',
            'PlyDonkey': 'DK',
            'PlyFox': 'Fox',
            'PlyGame': 'Mr. Game & Watch',
            'PlyKirby': 'Kirby',
            'PlyKoopa': 'Bowser',
            'PlyGkoopa': 'Giga Bowser',
            'PlyLink': 'Link',
            'PlyLuigi': 'Luigi',
            'PlyMario': 'Mario',
            'PlyMars': 'Marth',
            'PlyMewtwo': 'Mewtwo',
            'PlyNess': 'Ness',
            'PlyPeach': 'Peach',
            'PlyPichu': 'Pichu',
            'PlyPikachu': 'Pikachu',
            'PlyPurin': 'Jigglypuff',
            'PlySamus': 'Samus',
            'PlySeak': 'Sheik',
            'PlyYoshi': 'Yoshi',
            'PlyZelda': 'Zelda',
            'PlyPopo': 'Ice Climbers',
            'PlyNana': 'Ice Climbers (Nana)',
            'PlyBoy': 'Wireframe Male',
            'PlyGirl': 'Wireframe Female',
            'PlyGanon': 'Ganondorf',
            'PlyEmblem': 'Roy',
            'PlyFalco': 'Falco',
            'PlyMarioD': 'Dr. Mario',
            'PlyClink': 'Young Link',
            'PlyDrmario': 'Dr. Mario',
        }
        
        # Look for character data in root nodes
        for node in self.root_nodes:
            symbol = node['symbol']
            
            # Check if it's a character file
            for key, character in character_map.items():
                if key in symbol:
                    return character, symbol
                    
        return None, None
    
    def detect_costume_color(self):
        """Detect costume color from filename or symbol patterns"""
        
        # Complete color mapping based on PlXxYy format where Xx is character, Yy is color
        complete_color_map = {
            # Standard color codes (appear after character code)
            'Nr': 'Default',
            'Bu': 'Blue',
            'Re': 'Red',
            'Rd': 'Red',
            'Gr': 'Green',
            'Ye': 'Yellow',
            'Bk': 'Black',
            'Wh': 'White',
            'Pi': 'Pink',
            'Or': 'Orange',
            'La': 'Lavender',
            'Aq': 'Aqua/Light Blue',
            'Gy': 'Grey',
        }
        
        # First check the root node symbols for color codes
        for node in self.root_nodes:
            symbol = node['symbol']
            # Look for PlXxYy pattern (e.g., PlyPichu5K, PlFxGr, etc)
            if symbol.startswith('Ply') or symbol.startswith('Pl'):
                # Extract the color code - it's after the character code
                # Character codes are 2 letters after Pl/Ply (Ca, Pc, Ys, etc)
                import re
                # Match Pl or Ply, then 2-char character code, then 2-char color code
                match = re.search(r'Pl[y]?([A-Z][a-z])([A-Z][a-z])', symbol)
                if match:
                    color_code = match.group(2)
                    if color_code in complete_color_map:
                        return complete_color_map[color_code]
                        
                # Also check for patterns like PlyYoshi5KYe where color is at the end
                # Try different patterns - PlyYoshi5KYe has Ye after 5K
                match = re.search(r'Ply[A-Za-z]+5K([A-Z][a-z])', symbol)
                if match:
                    color_code = match.group(1)
                    if color_code in complete_color_map:
                        return complete_color_map[color_code]

                # Check for patterns like PlyPurin5K_Share_joint (no color code = default)
                if re.search(r'Ply[A-Za-z]+5K_Share_joint', symbol):
                    return 'Default'
        
        # Fallback: check filename for color patterns
        filename = os.path.basename(self.filepath).lower()
        
        # Check for color codes in filename (e.g., "pichu nr.dat")  
        for code, color in complete_color_map.items():
            if code.lower() in filename:
                # Make sure it's separated from character name
                if ' ' + code.lower() in filename or code.lower() + '.' in filename:
                    return color
                    
        return 'Unknown Color'

    def is_character_costume(self):
        """
        Determine if this is a character costume file (PlXxYy) vs a data/effect mod (PlXx).

        Character costume files have Ply symbols like:
        - PlyCaptain5KWh_Share_joint (Falcon White costume)
        - PlyMars5KNr_Share_joint (Marth Default costume)

        Data/effect mods only have ftData symbols:
        - ftDataMars (Marth data mod, no costume)

        Returns:
            bool: True if this is a character costume file, False if it's a data mod
        """
        # Check if any root node has a Ply symbol
        for node in self.root_nodes:
            symbol = node['symbol']
            if symbol.startswith('Ply'):
                return True

        # No Ply symbols found = data mod, not a costume
        return False

    def get_character_filename(self):
        """
        Get the proper Melee character filename (e.g., PlFxGr.dat for Fox Green).
        Returns the filename without .dat extension, or None if cannot be determined.
        """
        character, symbol = self.detect_character()
        color = self.detect_costume_color()

        if not character:
            return None

        # Character code mapping (character name -> 2-letter code)
        char_codes = {
            'C. Falcon': 'Ca',
            'DK': 'Dk',
            'Fox': 'Fx',
            'Mr. Game & Watch': 'Gw',
            'Kirby': 'Kb',
            'Bowser': 'Kp',
            'Giga Bowser': 'Gk',
            'Link': 'Lk',
            'Luigi': 'Lg',
            'Mario': 'Mr',
            'Marth': 'Ms',
            'Mewtwo': 'Mt',
            'Ness': 'Ns',
            'Peach': 'Pe',
            'Pichu': 'Pc',
            'Pikachu': 'Pk',
            'Jigglypuff': 'Pr',
            'Samus': 'Ss',
            'Sheik': 'Sk',
            'Yoshi': 'Ys',
            'Zelda': 'Zd',
            'Ice Climbers': 'Pp',
            'Ice Climbers (Nana)': 'Nn',
            'Young Link': 'Cl',
            'Wireframe Male': 'Bo',
            'Wireframe Female': 'Gl',
            'Master Hand': 'Mh',
            'Crazy Hand': 'Ch',
            'Sandbag': 'Sb',
            'Ganondorf': 'Gn',
            'Roy': 'Fe',
            'Falco': 'Fc',
            'Dr. Mario': 'Dr',
        }

        # Color code mapping (color name -> 2-letter code)
        color_codes = {
            'Default': 'Nr',
            'Blue': 'Bu',
            'Red': 'Re',
            'Green': 'Gr',
            'Yellow': 'Ye',
            'Black': 'Bk',
            'White': 'Wh',
            'Pink': 'Pi',
            'Orange': 'Or',
            'Lavender': 'La',
            'Aqua/Light Blue': 'Aq',
            'Grey': 'Gy',
        }

        char_code = char_codes.get(character)
        color_code = color_codes.get(color, 'Nr')  # Default to Nr if color unknown

        if not char_code:
            return None

        return f"Pl{char_code}{color_code}"

def main():
    if len(sys.argv) < 2:
        # If no argument, process both dat files in directory
        dat_files = ['pichu nr.dat', 'yoshi ys.dat']
    else:
        dat_files = sys.argv[1:]
    
    for filepath in dat_files:
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            continue
            
        print(f"\n{'='*50}")
        print(f"Analyzing: {filepath}")
        print('='*50)
        
        parser = DATParser(filepath)
        
        try:
            parser.read_dat()
            
            # Detect character
            character, symbol = parser.detect_character()
            
            if character:
                print(f"Character: {character}")
                print(f"Symbol: {symbol}")
            else:
                print("Character: Unknown (might be a stage or other file)")
                
            # Detect costume color
            color = parser.detect_costume_color()
            print(f"Costume Color: {color}")
            
            # Print all root nodes for debugging
            print("\nRoot Nodes found:")
            for node in parser.root_nodes:
                print(f"  - {node['symbol']}")
                
        except Exception as e:
            print(f"Error parsing file: {e}")

if __name__ == "__main__":
    main()
