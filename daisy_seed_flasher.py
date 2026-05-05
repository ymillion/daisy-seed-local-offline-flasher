#!/usr/bin/env python3
"""
Daisy Seed Offline Flasher
A generic offline GUI for managing and flashing firmware to Daisy Seed devices.
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import subprocess
import sys
import os
import json
import glob
import platform
import webbrowser
import urllib.request
import urllib.error
import threading
import re
import tarfile
from pathlib import Path

# Base directory: works both as a normal script and as a PyInstaller bundle
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).parent

# When Synthux repository is set up, change this to "https://raw.githubusercontent.com/.../firmwares_manifest.json"
MANIFEST_URL = (BASE_DIR / "firmwares_manifest.json").as_uri()
APP_VERSION = "1.0"




class DaisySeedFlasher:
    def __init__(self, root):
        self.root = root
        self.root.title("Daisy Seed Offline Flasher")
        self.root.geometry("1300x600")
        self.root.minsize(1300, 550)
        
        # Load app icon
        icon_path = BASE_DIR / 'img' / 'daisy-seed.png'
        if icon_path.exists():
            icon_img = tk.PhotoImage(file=str(icon_path))
            self.root.wm_iconphoto(True, icon_img)
        
        # Setup styles
        self.style = ttk.Style()
        self.style.configure("Title.TLabel", font=("Helvetica", 16, "bold"))
        self.style.configure("Subtitle.TLabel", font=("Helvetica", 12))
        self.style.configure("Flash.TButton", font=("Helvetica", 12, "bold"))
        
        # Firmware directory
        self.firmware_dir = BASE_DIR / "firmwares"
        self.firmware_dir.mkdir(exist_ok=True)
        
        # Track selected firmware
        self.selected_firmware = None
        self.bin_path = None
        self.is_flashing = False
        
        self._create_ui()
        self._scan_firmwares()
        self._check_dfu_util()
        
        # Start connection polling
        self.root.after(1000, self._poll_device_connection)
        
    def _create_ui(self):
        # Main container with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        
        main_frame.columnconfigure(0, weight=3, uniform="col") # Firmwares
        main_frame.columnconfigure(1, weight=3, uniform="col") # Details
        main_frame.columnconfigure(2, weight=3, uniform="col") # Flash
        main_frame.columnconfigure(3, weight=4, uniform="col") # Console
        main_frame.rowconfigure(1, weight=1)
        
        # Title
        title = ttk.Label(main_frame, text="Daisy Seed Offline Flasher", style="Title.TLabel")
        title.grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))
        
        # Connection status indicator at the top right
        conn_frame = ttk.Frame(main_frame)
        conn_frame.grid(row=0, column=2, columnspan=2, sticky=tk.E, pady=(0, 10))
        
        self.connection_canvas = tk.Canvas(conn_frame, width=16, height=16, highlightthickness=0)
        self.connection_canvas.pack(side=tk.LEFT, padx=(0, 5))
        self.indicator = self.connection_canvas.create_oval(2, 2, 14, 14, fill="#9E9E9E", outline="#757575")
        
        self.conn_label = ttk.Label(conn_frame, text="Device Disconnected", font=("Helvetica", 10), foreground="gray")
        self.conn_label.pack(side=tk.LEFT)
        
        # COL 0: Firmware list
        left_frame = ttk.LabelFrame(main_frame, text="Available Firmwares", padding="5")
        left_frame.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(0, 5))
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(0, weight=1)
        
        self.firmware_list = tk.Listbox(left_frame, font=("Helvetica", 11), width=10)
        scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=self.firmware_list.yview)
        self.firmware_list.configure(yscrollcommand=scrollbar.set)
        
        self.firmware_list.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        
        self.firmware_list.bind('<<ListboxSelect>>', self._on_firmware_select)
        
        btn_frame = ttk.Frame(left_frame)
        btn_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(10, 0))
        
        ttk.Button(btn_frame, text="Browse for .bin...", command=self._browse_firmware).pack(side=tk.TOP, fill=tk.X, pady=(0, 5))
        ttk.Button(btn_frame, text="Open Firmware Folder", command=self._open_firmware_folder).pack(side=tk.TOP, fill=tk.X, pady=(0, 10))
        
        self.sync_btn = ttk.Button(btn_frame, text="Sync from Synthux Github", command=self._sync_firmwares)
        self.sync_btn.pack(side=tk.TOP, fill=tk.X, pady=(0, 5))
        
        self.sync_status = ttk.Label(btn_frame, text="", font=("Helvetica", 9), foreground="blue")
        self.sync_status.pack(side=tk.TOP, fill=tk.X)
        
        # COL 1: Firmware Details
        details_frame = ttk.LabelFrame(main_frame, text="Firmware Details", padding="10")
        details_frame.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(5, 5))
        details_frame.columnconfigure(0, weight=1)
        details_frame.rowconfigure(0, weight=1)
        
        self.details_text = scrolledtext.ScrolledText(
            details_frame, 
            wrap=tk.WORD, 
            font=("Helvetica", 10),
            state=tk.DISABLED,
            width=10
        )
        self.details_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure Markdown styles
        self.details_text.tag_configure("h1", font=("Helvetica", 14, "bold"), spacing1=10, spacing3=5)
        self.details_text.tag_configure("h2", font=("Helvetica", 11, "bold"), spacing1=8, spacing3=3)
        self.details_text.tag_configure("bold", font=("Helvetica", 10, "bold"))
        self.details_text.tag_configure("bullet", lmargin1=15, lmargin2=25)
        self.details_text.tag_configure("body", font=("Helvetica", 10))
        
        self.edit_details_btn = ttk.Button(details_frame, text="Edit Firmware Info", command=self._edit_metadata)
        self.edit_details_btn.grid(row=1, column=0, sticky=tk.E, pady=(5, 0))
        self.edit_details_btn.configure(state=tk.DISABLED)
        
        # COL 2: Flash Firmware
        flash_frame = ttk.LabelFrame(main_frame, text="Flash Firmware", padding="10")
        flash_frame.grid(row=1, column=2, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(5, 5))
        flash_frame.columnconfigure(0, weight=1)
        
        self.status_label = ttk.Label(flash_frame, text="Select a firmware to flash", font=("Helvetica", 11), wraplength=260)
        self.status_label.grid(row=0, column=0, sticky=tk.W, pady=(0, 10))
        
        self.file_label = ttk.Label(flash_frame, text="No file selected", font=("Helvetica", 9), foreground="gray", wraplength=260)
        self.file_label.grid(row=1, column=0, sticky=tk.W, pady=(0, 20))
        
        self.flash_btn = ttk.Button(
            flash_frame, 
            text="FLASH TO DEVICE", 
            command=self._flash_firmware,
            style="Flash.TButton"
        )
        self.flash_btn.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 20))
        self.flash_btn.configure(state=tk.DISABLED)
        
        instructions = """Instructions:
1. To put Daisy in bootloader mode:
   - Connect Seed with USB cable
   - Press and hold BOOT button
   - Press and hold RESET button
   - Release RESET button
   - Release BOOT button
   - (Indicator at top-right will turn green)
2. Select firmware from list
3. Click "FLASH TO DEVICE"
4. Wait for completion, then reset"""
        
        inst_label = tk.Label(flash_frame, text=instructions, justify=tk.LEFT, font=("Helvetica", 9), wraplength=260)
        inst_label.grid(row=3, column=0, sticky=tk.W)
        
        # COL 3: Console Output
        console_frame = ttk.LabelFrame(main_frame, text="Console Output", padding="5")
        console_frame.grid(row=1, column=3, sticky=(tk.W, tk.E, tk.N, tk.S), padx=(5, 0))
        console_frame.columnconfigure(0, weight=1)
        console_frame.rowconfigure(0, weight=1)
        
        self.console = scrolledtext.ScrolledText(
            console_frame,
            wrap=tk.WORD,
            font=("Courier", 9),
            state=tk.DISABLED,
            bg="#1e1e1e",
            fg="#d4d4d4",
            width=10
        )
        self.console.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # DFU status spanning bottom
        dfu_frame = ttk.Frame(main_frame)
        dfu_frame.grid(row=2, column=0, columnspan=3, sticky=tk.W, pady=(10, 0))
        
        self.dfu_status = ttk.Label(dfu_frame, text="Checking dfu-util...", font=("Helvetica", 9))
        self.dfu_status.pack(side=tk.LEFT)
        
        self.dfu_install_btn = ttk.Button(dfu_frame, text="Auto-Install dfu-util", command=self._auto_install_dfu)
        # the button will be packed if dfu-util is not found

        if platform.system() == "Windows":
            self.zadig_btn = ttk.Button(dfu_frame, text="Install USB Driver (Zadig)", command=self._download_and_open_zadig)
            self.zadig_btn.pack(side=tk.LEFT, padx=(10, 0))
        
        # Version
        version_lbl = ttk.Label(main_frame, text=f"v{APP_VERSION}", font=("Helvetica", 9), foreground="gray")
        version_lbl.grid(row=2, column=0, columnspan=4, pady=(10, 0))

        # Credits
        credits_lbl = tk.Label(main_frame, text="Credits: StubeMusic", font=("Helvetica", 9, "underline"), fg="#0066cc", cursor="hand2")
        credits_lbl.grid(row=2, column=3, sticky=tk.E, pady=(10, 0))
        credits_lbl.bind("<Button-1>", lambda e: webbrowser.open_new("https://www.youtube.com/@StubeMusicMedia"))

    def _log(self, message, tag=None):
        """Add message to console"""
        self.console.configure(state=tk.NORMAL)
        self.console.insert(tk.END, message + "\n", tag)
        self.console.see(tk.END)
        self.console.configure(state=tk.DISABLED)
        self.root.update_idletasks()
        
    def _scan_firmwares(self):
        """Scan firmware directory for .bin files and list them"""
        self.firmware_list.delete(0, tk.END)
        
        # Look for .bin files recursively
        bin_files = sorted(self.firmware_dir.rglob("*.bin"), key=lambda p: p.name.lower())
        
        # Store the mapping from display name to full path
        self._firmware_paths = {}
        
        for bin_file in bin_files:
            # Get relative path for display (show subfolder if nested)
            try:
                rel_path = bin_file.relative_to(self.firmware_dir)
                display_name = str(rel_path).replace("\\", "/")
            except ValueError:
                display_name = bin_file.name
            
            # Add to list and get index
            self.firmware_list.insert(tk.END, display_name)
            idx = self.firmware_list.size() - 1  # Index of the item just added
            self._firmware_paths[display_name] = bin_file
            
            # Check if we have an accompanying .md file for this firmware
            has_metadata = bin_file.with_suffix(".md").exists()
            
            if has_metadata:
                self.firmware_list.itemconfig(idx, {'bg': '#e8f5e9'})  # Light green
            else:
                self.firmware_list.itemconfig(idx, {'bg': '#fff9c4'})  # Light yellow - unknown
        
        if not bin_files:
            self._log("No .bin files found in firmwares/ folder")
            self._log("Place .bin files in: " + str(self.firmware_dir))
            self.firmware_list.insert(tk.END, "No firmwares found - click 'Browse for .bin...'")
            
    def _on_firmware_select(self, event):
        """Handle firmware selection"""
        selection = self.firmware_list.curselection()
        if not selection:
            return
            
        display_name = self.firmware_list.get(selection[0])
        self.selected_firmware = display_name
        
        # Get the path from our mapping
        if hasattr(self, '_firmware_paths') and display_name in self._firmware_paths:
            self.bin_path = self._firmware_paths[display_name]
            self.file_label.configure(text=f"Selected: {self.bin_path.name}")
            self.flash_btn.configure(state=tk.NORMAL)
            self.status_label.configure(text=f"Ready to flash {self.bin_path.name}")
            
            if hasattr(self, 'edit_details_btn'):
                self.edit_details_btn.configure(state=tk.NORMAL)
            
            md_path = self.bin_path.with_suffix('.md')
            if md_path.exists():
                self._show_firmware_details(md_path)
            else:
                self._show_unknown_firmware(self.bin_path)
        else:
            self.bin_path = None
            self.file_label.configure(text="No .bin file selected")
            self.flash_btn.configure(state=tk.DISABLED)
            self.status_label.configure(text="Select a .bin file to continue")
        
    def _show_firmware_details(self, md_path):
        """Display firmware details from markdown file with basic styling"""
        self.details_text.configure(state=tk.NORMAL)
        self.details_text.delete(1.0, tk.END)
        
        try:
            with open(md_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            for line in lines:
                line = line.rstrip()
                
                # Strip HTML tags (like <img ... />)
                line = re.sub(r'<[^>]+>', '', line)
                
                if not line.strip():
                    self.details_text.insert(tk.END, "\n")
                    continue
                
                # Headers
                if line.startswith("# "):
                    self.details_text.insert(tk.END, line[2:] + "\n", "h1")
                elif line.startswith("## "):
                    self.details_text.insert(tk.END, line[3:] + "\n", "h2")
                elif line.startswith("### "):
                    self.details_text.insert(tk.END, line[4:] + "\n", "h2")
                # Lists
                elif line.startswith("- ") or line.startswith("* "):
                    self._insert_styled_text("  • " + line[2:] + "\n", "bullet")
                else:
                    self._insert_styled_text(line + "\n")
                    
        except Exception as e:
            self.details_text.insert(tk.END, f"Error reading {md_path.name}:\n{e}")
            
        self.details_text.configure(state=tk.DISABLED)

    def _insert_styled_text(self, text, base_tag=None):
        """Helper to insert text and handle inline bolding/links"""
        # Simple Bold parsing: **text**
        parts = re.split(r'(\*\*.*?\*\*)', text)
        for part in parts:
            if part.startswith("**") and part.endswith("**"):
                content = part[2:-2]
                tags = ("bold", base_tag) if base_tag else "bold"
                self.details_text.insert(tk.END, content, tags)
            else:
                # Handle links [text](url) -> text
                clean_part = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', part)
                self.details_text.insert(tk.END, clean_part, base_tag if base_tag else "body")

    def _show_unknown_firmware(self, bin_path):
        """Display info for firmware without metadata using unified tags"""
        self.details_text.configure(state=tk.NORMAL)
        self.details_text.delete(1.0, tk.END)
        
        self.details_text.insert(tk.END, bin_path.name + "\n", "h1")
        self.details_text.insert(tk.END, "Custom/Unknown Firmware\n\n", "body")
        
        # Show file info
        size = bin_path.stat().st_size
        self.details_text.insert(tk.END, "File Info:\n", "h2")
        self.details_text.insert(tk.END, f"  Name: {bin_path.name}\n", "body")
        self.details_text.insert(tk.END, f"  Size: {size:,} bytes ({size/1024:.1f} KB)\n", "body")
        self.details_text.insert(tk.END, f"  Path: {bin_path.parent}\n\n", "body")
        
        self.details_text.insert(tk.END, "Note: ", "h2")
        self.details_text.insert(tk.END, "This firmware doesn't have built-in documentation. "
                                       "You can click 'Edit Firmware Info' below to add it, or visit the "
                                       "official Synthux-Academy GitHub to find the description.\n", "body")
        
        self.details_text.configure(state=tk.DISABLED)

    def _edit_metadata(self):
        if not hasattr(self, 'bin_path') or not self.bin_path:
            return
            
        md_path = self.bin_path.with_suffix('.md')
        
        existing_data = ""
        if md_path.exists():
            with open(md_path, 'r', encoding='utf-8') as f:
                existing_data = f.read()
        else:
            existing_data = f"# {self.bin_path.stem}\n\nAdd description here...\n"
        
        editor = tk.Toplevel(self.root)
        editor.title(f"Edit Documentation - {md_path.name}")
        editor.geometry("650x550")
        editor.transient(self.root)
        editor.grab_set()
        
        lbl = ttk.Label(editor, text="Edit firmware documentation (Markdown format):")
        lbl.pack(anchor=tk.W, padx=10, pady=(10, 0))
        
        text_area = scrolledtext.ScrolledText(editor, font=("Courier", 10), wrap=tk.WORD)
        text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        
        text_area.insert(tk.END, existing_data)
        
        btn_frame = ttk.Frame(editor)
        btn_frame.pack(fill=tk.X, padx=10, pady=10)
        
        def save():
            new_data = text_area.get(1.0, tk.END).strip()
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write(new_data)
            
            self._show_firmware_details(md_path) 
            self._scan_firmwares()
            editor.destroy()
                
        ttk.Button(btn_frame, text="Save", command=save).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(btn_frame, text="Cancel", command=editor.destroy).pack(side=tk.RIGHT)
        
    def _sync_firmwares(self):
        """Fetch manifest and show selection modal"""
        self.sync_btn.configure(state=tk.DISABLED)
        self.sync_status.configure(text="Fetching manifest...", foreground="blue")
        
        def fetch_task():
            try:
                self._log(f"\nFetching manifest from: {MANIFEST_URL}")
                with urllib.request.urlopen(MANIFEST_URL) as response:
                    manifest_data = json.loads(response.read().decode('utf-8'))
                self.root.after(0, lambda: self._show_sync_selection_modal(manifest_data))
            except Exception as e:
                self._log(f"Failed to fetch manifest: {e}")
                self.root.after(0, lambda: self.sync_status.configure(text="Fetch failed", foreground="red"))
                self.root.after(0, lambda: self.sync_btn.configure(state=tk.NORMAL))

        thread = threading.Thread(target=fetch_task)
        thread.daemon = True
        thread.start()

    def _show_sync_selection_modal(self, manifest_data):
        """Show a modal to select firmwares for syncing"""
        self.sync_status.configure(text="")
        self.sync_btn.configure(state=tk.NORMAL)
        
        modal = tk.Toplevel(self.root)
        modal.title("Select Firmwares to Sync")
        modal.geometry("500x500")
        modal.transient(self.root)
        modal.grab_set()
        
        main_frame = ttk.Frame(modal, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(main_frame, text="Select the firmwares you want to download:", font=("Helvetica", 11, "bold")).pack(anchor=tk.W, pady=(0, 10))
        
        # Scrollable area for firmware list
        list_frame = ttk.Frame(main_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        canvas = tk.Canvas(list_frame)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        
        firmwares = manifest_data.get('firmwares', [])
        vars_dict = {} # Map firmware ID to BooleanVar
        
        for fw in firmwares:
            fid = fw.get('id')
            name = fw.get('name', fid)
            
            bin_path = self.firmware_dir / f"{fid}.bin"
            is_local = bin_path.exists()
            
            var = tk.BooleanVar(value=not is_local) # Default: check if NOT local
            vars_dict[fid] = var
            
            row = ttk.Frame(scrollable_frame)
            row.pack(fill=tk.X, pady=2)
            
            cb = ttk.Checkbutton(row, text=name, variable=var)
            cb.pack(side=tk.LEFT)
            
            if is_local:
                ttk.Label(row, text="(Already local)", font=("Helvetica", 8), foreground="gray").pack(side=tk.LEFT, padx=5)
            else:
                ttk.Label(row, text="(New)", font=("Helvetica", 8), foreground="green").pack(side=tk.LEFT, padx=5)

        # Bottom buttons
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(15, 0))
        
        def select_all():
            for v in vars_dict.values(): v.set(True)
        
        def select_none():
            for v in vars_dict.values(): v.set(False)

        ttk.Button(btn_frame, text="Select All", command=select_all).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(btn_frame, text="Select None", command=select_none).pack(side=tk.LEFT)

        def start_sync():
            selected = [fw for fw in firmwares if vars_dict[fw.get('id')].get()]
            if not selected:
                messagebox.showwarning("Selection Empty", "Please select at least one firmware to sync.")
                return
            
            modal.destroy()
            self._log(f"\n--- Starting Cloud Sync ({len(selected)} items) ---")
            self.sync_btn.configure(state=tk.DISABLED)
            self.sync_status.configure(text="Syncing... Please wait.", foreground="blue")
            
            thread = threading.Thread(target=self._sync_worker, args=(selected,))
            thread.daemon = True
            thread.start()

        ttk.Button(btn_frame, text="Sync Selected", command=start_sync, style="Flash.TButton").pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Cancel", command=modal.destroy).pack(side=tk.RIGHT, padx=5)

    def _sync_worker(self, selected_firmwares):
        results = []
        try:
            for fw in selected_firmwares:
                fid = fw.get('id')
                bin_url = fw.get('bin_url')
                md_url = fw.get('md_url')
                
                if not fid or not bin_url:
                    continue
                    
                bin_path = self.firmware_dir / f"{fid}.bin"
                md_path = self.firmware_dir / f"{fid}.md"
                
                # Download bin
                self._log(f"Downloading {fid}.bin ...")
                try:
                    urllib.request.urlretrieve(bin_url, str(bin_path))
                    results.append(f"✓ Downloaded {fid}.bin")
                except Exception as e:
                    self._log(f"Failed to download {fid}.bin: {e}")
                    results.append(f"✗ Failed {fid}.bin")
                
                # Download md
                if md_url:
                    try:
                        self._log(f"Downloading {fid}.md ...")
                        urllib.request.urlretrieve(md_url, str(md_path))
                        # results.append(f"✓ Downloaded {fid}.md") # Don't clutter results too much
                    except Exception as e:
                        self._log(f"Failed to download MD for {fid}: {e}")
                        
            if not results:
                results.append("No firmwares were updated.")
                
        except Exception as e:
            results.append(f"Sync failed: {e}")
            
        self.root.after(0, self._sync_complete, results)

    def _sync_complete(self, results):
        self.sync_btn.configure(state=tk.NORMAL)
        self.sync_status.configure(text="")
        for r in results:
            self._log(r)
        self._log("--- Cloud Sync Finished ---")
        self._scan_firmwares()

    def _browse_firmware(self):
        """Open file browser for .bin file"""
        filename = filedialog.askopenfilename(
            title="Select firmware .bin file",
            filetypes=[("Binary files", "*.bin"), ("All files", "*.*")]
        )
        if filename:
            self.bin_path = Path(filename)
            self.file_label.configure(text=f"Selected: {self.bin_path.name}")
            self.flash_btn.configure(state=tk.NORMAL)
            self.status_label.configure(text="Ready to flash")
            
            md_path = self.bin_path.with_suffix('.md')
            if md_path.exists():
                self._show_firmware_details(md_path)
            else:
                self._show_unknown_firmware(self.bin_path)
                
            if hasattr(self, 'edit_details_btn'):
                self.edit_details_btn.configure(state=tk.NORMAL)
                    
    def _open_firmware_folder(self):
        """Open firmware directory in file explorer"""
        if platform.system() == "Windows":
            os.startfile(self.firmware_dir)
        elif platform.system() == "Darwin":  # macOS
            subprocess.run(["open", self.firmware_dir])
        else:  # Linux
            subprocess.run(["xdg-open", self.firmware_dir])
            
    def _get_dfu_cmd(self, *args):
        # Determine dfu-util binary path
        cmd = ["dfu-util"]
        system = platform.system()
        
        base_dir = BASE_DIR / "bin" / "dfu-util" / "dfu-util-0.11-binaries"
        local_dfu = None
        
        if system == "Windows":
            local_dfu = base_dir / "win64" / "dfu-util.exe"
        elif system == "Darwin":
            local_dfu = base_dir / "darwin-x86_64" / "dfu-util"
        elif system == "Linux":
            local_dfu = base_dir / "linux-amd64" / "dfu-util"
            
        if local_dfu and local_dfu.exists():
            cmd = [str(local_dfu)]
            
        cmd.extend(args)
        return cmd

    def _auto_install_dfu(self):
        """Downloads and extracts dfu-util for all platforms."""
        self.dfu_install_btn.pack_forget()
        self.dfu_status.configure(text="Downloading dfu-util (this may take a moment)...", foreground="blue")
        
        def install_task():
            try:
                url = "https://sourceforge.net/projects/dfu-util/files/dfu-util-0.11-binaries.tar.xz/download"
                download_path = BASE_DIR / "dfu-util-download.tar.xz"
                
                self._log("Downloading dfu-util-0.11-binaries.tar.xz from Sourceforge...")
                urllib.request.urlretrieve(url, str(download_path))
                
                self._log("Extracting dfu-util...")
                extract_dir = BASE_DIR / "bin" / "dfu-util"
                extract_dir.mkdir(parents=True, exist_ok=True)
                
                with tarfile.open(download_path, "r:xz") as tar:
                    # filter is added natively in Python 3.12, but for older we just extractall
                    if hasattr(tarfile, 'data_filter'):
                        tar.extractall(path=str(extract_dir), filter='data')
                    else:
                        tar.extractall(path=str(extract_dir))
                
                # Make binaries executable on Mac/Linux
                if platform.system() in ("Darwin", "Linux"):
                    import stat
                    for exe_path in extract_dir.rglob("dfu-util*"):
                        if exe_path.is_file():
                            st = os.stat(exe_path)
                            os.chmod(exe_path, st.st_mode | stat.S_IEXEC)
                    
                download_path.unlink() # Cleanup
                self.root.after(0, self._check_dfu_util)
                self._log("dfu-util Auto-Install completed successfully!")
            except Exception as e:
                self._log(f"Auto-Install failed: {e}")
                self.root.after(0, lambda: self.dfu_status.configure(text="Auto-Install Failed", foreground="red"))
                self.root.after(0, lambda: self.dfu_install_btn.pack(side=tk.LEFT, padx=(10, 0)))

        thread = threading.Thread(target=install_task)
        thread.daemon = True
        thread.start()

    def _download_and_open_zadig(self):
        """Download Zadig (if needed) and launch it so the user can install the WinUSB driver."""
        zadig_path = BASE_DIR / "bin" / "zadig.exe"
        zadig_url = "https://github.com/pbatard/libwdi/releases/download/v1.5.1/zadig-2.9.exe"

        def task():
            try:
                if not zadig_path.exists():
                    self.root.after(0, lambda: self.zadig_btn.configure(state=tk.DISABLED, text="Downloading Zadig..."))
                    self._log("Downloading Zadig...")
                    zadig_path.parent.mkdir(parents=True, exist_ok=True)
                    urllib.request.urlretrieve(zadig_url, str(zadig_path))
                    self._log("Zadig downloaded successfully.")
                else:
                    self._log(f"Using existing Zadig: {zadig_path}")

                self._log("Launching Zadig (may request administrator access)...")
                self._log("In Zadig: select 'STM32 BOOTLOADER' and click 'Install Driver'.")
                os.startfile(str(zadig_path), 'runas')
                self.root.after(0, lambda: self.zadig_btn.configure(state=tk.NORMAL, text="Install USB Driver (Zadig)"))
            except Exception as e:
                self._log(f"Zadig error: {e}")
                self.root.after(0, lambda: self.zadig_btn.configure(state=tk.NORMAL, text="Install USB Driver (Zadig)"))
                self.root.after(0, lambda err=e: messagebox.showerror("Zadig Error", f"Failed to download or launch Zadig:\n{err}"))

        thread = threading.Thread(target=task)
        thread.daemon = True
        thread.start()

    def _check_dfu_util(self):
        """Check if dfu-util is available"""
        cmd = self._get_dfu_cmd("--version")
        try:
            # Hide console window on Windows
            kwargs = {}
            if platform.system() == "Windows":
                kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
                
            result = subprocess.run(cmd, 
                                  capture_output=True, text=True, **kwargs)
            if result.returncode == 0:
                version = result.stdout.split('\n')[0]
                self.dfu_status.configure(text=f"✓ Local {version}" if "bin" in cmd[0] else f"✓ System {version}", foreground="green")
                if hasattr(self, 'dfu_install_btn') and self.dfu_install_btn.winfo_ismapped():
                    self.dfu_install_btn.pack_forget()
            else:
                self.dfu_status.configure(text="✗ dfu-util not working", foreground="red")
        except FileNotFoundError:
            self.dfu_status.configure(text="✗ dfu-util not found.", foreground="red")
            self.dfu_install_btn.pack(side=tk.LEFT, padx=(10, 0))
            
    def _list_dfu_devices(self):
        """Run dfu-util -l and parse all found devices into a list of dicts.
        Each dict has keys: type ('DFU' or 'Runtime'), vid_pid, path, name, serial, raw."""
        devices = []
        try:
            kwargs = {}
            if platform.system() == "Windows":
                kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            cmd = self._get_dfu_cmd("-l")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, **kwargs)
            
            seen_serials = set()
            for line in result.stdout.splitlines():
                # Match lines like: Found DFU: [0483:df11] ... serial="200364500000"
                #               or: Found Runtime: [30c9:00ac] ... serial="01.00.00"
                m = re.match(
                    r'Found\s+(DFU|Runtime):\s+\[([0-9a-fA-F:]+)\].*?'
                    r'path="([^"]*)".*?name="([^"]*)".*?serial="([^"]*)"',
                    line
                )
                if m:
                    vid_pid = m.group(2).lower()
                    serial = m.group(5)
                    # Filter by STM32 bootloader VID:PID (0483:df11) used by Daisy Seed.
                    # This ignores other USB devices like webcams that might have DFU Runtime interfaces.
                    if vid_pid == "0483:df11":
                        if serial not in seen_serials:
                            seen_serials.add(serial)
                            devices.append({
                                'type': m.group(1),
                                'vid_pid': vid_pid,
                                'path': m.group(3),
                                'name': m.group(4),
                                'serial': serial,
                                'raw': line.strip()
                            })
        except Exception:
            pass
        return devices

    def _poll_device_connection(self):
        """Periodically poll dfu-util to check if device is connected in DFU mode"""
        if not self.is_flashing:
            def poll_task():
                try:
                    devices = self._list_dfu_devices()
                    dfu_devices = [d for d in devices if d['type'] == 'DFU']
                    runtime_devices = [d for d in devices if d['type'] == 'Runtime']
                    self.root.after(0, lambda: self._update_connection_ui(dfu_devices, runtime_devices))
                except Exception:
                    self.root.after(0, lambda: self._update_connection_ui([], []))
            thread = threading.Thread(target=poll_task, daemon=True)
            thread.start()
                
        # Poll again in 3 seconds
        self.root.after(3000, self._poll_device_connection)

    def _update_connection_ui(self, dfu_devices, runtime_devices):
        """Update connection indicator on the main thread"""
        if dfu_devices:
            count = len(dfu_devices)
            label = f"{count} Device{'s' if count > 1 else ''} in DFU Mode"
            if runtime_devices:
                label += f" (+{len(runtime_devices)} idle)"
            self.connection_canvas.itemconfig(self.indicator, fill="#4CAF50", outline="#388E3C")
            self.conn_label.configure(text=label, foreground="#4CAF50")
        elif runtime_devices:
            count = len(runtime_devices)
            self.connection_canvas.itemconfig(self.indicator, fill="#FFA726", outline="#F57C00") # Orange
            self.conn_label.configure(
                text=f"{count} Device{'s' if count > 1 else ''} Connected — To enter DFU: Hold BOOT + Tap RESET",
                foreground="#F57C00"
            )
        else:
            self.connection_canvas.itemconfig(self.indicator, fill="#9E9E9E", outline="#757575")
            self.conn_label.configure(text="Device Disconnected", foreground="gray")

    def _flash_firmware(self):
        """Flash the selected firmware to device"""
        if not self.bin_path:
            messagebox.showerror("Error", "No firmware file selected")
            return
            
        if not self.bin_path.exists():
            messagebox.showerror("Error", f"File not found: {self.bin_path}")
            return
        
        # Enumerate connected DFU devices to handle multi-device scenarios
        devices = self._list_dfu_devices()
        dfu_devices = [d for d in devices if d['type'] == 'DFU']
        
        target_serial = None
        
        if len(dfu_devices) == 0:
            messagebox.showerror("No DFU Device",
                "No Daisy Seed device in DFU mode detected.\n\n"
                "To enter DFU mode:\n"
                "1. Press and hold BOOT button\n"
                "2. Press and hold RESET button\n"
                "3. Release RESET button\n"
                "4. Release BOOT button")
            return
        elif len(dfu_devices) == 1:
            target_serial = dfu_devices[0]['serial']
            self._log(f"Auto-selecting the device in DFU mode (serial: {target_serial})")
        else:
            # Multiple devices in DFU mode — ask the user to pick
            target_serial = self._show_device_picker(dfu_devices)
            if target_serial is None:
                return  # User cancelled
            
        self.flash_btn.configure(state=tk.DISABLED)
        self.is_flashing = True
        self.status_label.configure(text="Flashing... DO NOT DISCONNECT!")
        self._log(f"\n--- Starting flash: {self.bin_path.name} ---")
        self._log(f"Full path: {self.bin_path.absolute()}")
        
        # Build dfu-util command
        flash_args = ["-d", "0483:df11"]
        if target_serial:
            flash_args.extend(["-S", target_serial])
        flash_args.extend(["-a", "0", "-s", "0x08000000:leave", "-D", str(self.bin_path)])
        cmd = self._get_dfu_cmd(*flash_args)
        
        self._log(f"Command: {' '.join(cmd)}")
        
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Stream output to console
            for line in process.stdout:
                self._log(line.rstrip())
                
            process.wait()
            
            # Exit code 74 with ":leave" is a known dfu-util quirk:
            # the device resets before dfu-util can read final status.
            # If the download actually completed, treat it as success.
            output_str = self.console.get(1.0, tk.END)
            download_ok = "File downloaded successfully" in output_str or "Download done" in output_str
            
            if process.returncode == 0 or (process.returncode == 74 and download_ok):
                self._log("--- Flash completed successfully! ---")
                self.status_label.configure(text="Flash complete! Device is resetting.", foreground="green")
                messagebox.showinfo("Success", "Firmware flashed successfully!\n\nYour Daisy Seed should restart automatically with the new firmware.")
            else:
                self._log(f"--- Flash failed with code {process.returncode} ---")
                self.status_label.configure(text="Flash failed - check console", foreground="red")
                
                # Common error hints
                output_str = self.console.get(1.0, tk.END)
                if "No DFU capable USB device" in output_str:
                    self._log("\nHINT: To put Daisy in bootloader mode:")
                    self._log("- Connect Seed with USB cable")
                    self._log("- Press and hold BOOT button")
                    self._log("- Press and hold RESET button")
                    self._log("- Release RESET button")
                    self._log("- Release BOOT button")
                    messagebox.showerror("Device not found", 
                        "No device in DFU mode detected.\n\n"
                        "To enter DFU mode:\n"
                        "1. Press and hold BOOT button\n"
                        "2. Press and hold RESET button\n"
                        "3. Release RESET button\n"
                        "4. Release BOOT button")
                elif "More than one DFU capable USB device" in output_str:
                    self._log("\nHINT: Multiple DFU-capable devices found.")
                    self._log("Disconnect all Daisy Seeds except the one you want to flash, then retry.")
                    messagebox.showerror("Multiple Devices",
                        "Multiple DFU-capable USB devices are connected.\n\n"
                        "Please disconnect all Daisy Seeds except the one\n"
                        "you want to flash, then try again.")
                elif "Permission denied" in output_str or "access denied" in output_str.lower():
                    self._log("\nHINT: Try running with administrator/sudo privileges")
                    messagebox.showerror("Permission denied", 
                        "Access denied. Try running this application as administrator.")
                    
        except Exception as e:
            self._log(f"Error: {str(e)}")
            self.status_label.configure(text="Error during flash", foreground="red")
            messagebox.showerror("Error", f"Failed to flash: {str(e)}")
            
        finally:
            self.flash_btn.configure(state=tk.NORMAL)
            self.is_flashing = False

    def _show_device_picker(self, dfu_devices):
        """Show a modal dialog to let the user pick which DFU device to flash.
        Returns the selected serial string, or None if cancelled."""
        selected_serial = [None]  # mutable container for closure
        
        picker = tk.Toplevel(self.root)
        picker.title("Select DFU Device")
        picker.geometry("500x300")
        picker.transient(self.root)
        picker.grab_set()
        picker.resizable(False, False)
        
        frame = ttk.Frame(picker, padding="15")
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="Multiple devices in DFU mode detected.",
                  font=("Helvetica", 11, "bold")).pack(anchor=tk.W, pady=(0, 3))
        ttk.Label(frame, text="Select the device you want to flash:",
                  font=("Helvetica", 10)).pack(anchor=tk.W, pady=(0, 10))
        
        listbox = tk.Listbox(frame, font=("Courier", 10), height=8)
        listbox.pack(fill=tk.BOTH, expand=True)
        
        for i, dev in enumerate(dfu_devices):
            label = f"Device {i+1}:  serial={dev['serial']}  path={dev['path']}  [{dev['vid_pid']}]"
            listbox.insert(tk.END, label)
        
        listbox.selection_set(0)  # Pre-select first
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))
        
        def on_select():
            sel = listbox.curselection()
            if sel:
                selected_serial[0] = dfu_devices[sel[0]]['serial']
            picker.destroy()
        
        def on_cancel():
            picker.destroy()
        
        ttk.Button(btn_frame, text="Flash This Device", command=on_select, style="Flash.TButton").pack(side=tk.RIGHT)
        ttk.Button(btn_frame, text="Cancel", command=on_cancel).pack(side=tk.RIGHT, padx=(0, 5))
        
        picker.wait_window()
        return selected_serial[0]


def main():
    root = tk.Tk()
    app = DaisySeedFlasher(root)
    root.mainloop()


if __name__ == "__main__":
    main()
