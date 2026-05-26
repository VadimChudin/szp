import os
import shutil
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
import sys

def get_mt4_terminals() -> list[dict]:
    terminals = []
    terminal_base = Path(os.environ.get("APPDATA", "")) / "MetaQuotes" / "Terminal"
    if not terminal_base.exists():
        return terminals

    for sub in terminal_base.iterdir():
        if sub.is_dir() and len(sub.name) == 32:
            mql4_dir = sub / "MQL4"
            origin_file = sub / "origin.txt"
            if mql4_dir.exists() and origin_file.exists():
                try:
                    with open(origin_file, 'r', encoding='utf-16le') as f:
                        origin_path = f.read().strip()
                except:
                    try:
                        with open(origin_file, 'r', encoding='utf-8') as f:
                            origin_path = f.read().strip()
                    except:
                        origin_path = str(sub.name)
                
                terminals.append({
                    "id": sub.name,
                    "name": Path(origin_path).name,
                    "mql4": mql4_dir
                })
    return terminals

class InstallerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Smart Zones Pro - MT4 Patcher")
        self.geometry("400x300")
        self.configure(padx=20, pady=20)
        
        self.terminals = get_mt4_terminals()
        
        tk.Label(self, text="Select MetaTrader 4 Terminals to Patch:", font=("Arial", 12, "bold")).pack(anchor="w", pady=(0, 10))
        
        self.vars = []
        self.check_frame = tk.Frame(self)
        self.check_frame.pack(fill="both", expand=True)
        
        if not self.terminals:
            tk.Label(self.check_frame, text="No MT4 terminals found on this PC.", fg="red").pack(anchor="w")
        else:
            for term in self.terminals:
                var = tk.BooleanVar(value=True)
                self.vars.append((var, term))
                chk = tk.Checkbutton(self.check_frame, text=f"{term['name']} (ID: {term['id'][:8]}...)", variable=var)
                chk.pack(anchor="w", pady=2)
                
        btn_frame = tk.Frame(self)
        btn_frame.pack(fill="x", pady=20)
        
        tk.Button(btn_frame, text="Install / Patch", command=self.do_patch, bg="#4CAF50", fg="white", font=("Arial", 10, "bold"), width=15).pack(side="left")
        tk.Button(btn_frame, text="Cancel", command=self.destroy, width=10).pack(side="right")
        
    def do_patch(self):
        # We need to find the source MQL4 files. 
        # When running as an exe, they will be inside the data dir. But we'll safely locate them.
        base_dir = Path(__file__).parent.parent
        src_mql4 = base_dir / "mql" / "MT4"
        
        if not src_mql4.exists():
            messagebox.showerror("Error", f"Source MQL4 folder not found at:\n{src_mql4}")
            return
            
        success_count = 0
        for var, term in self.vars:
            if var.get():
                target_mql4 = term["mql4"]
                
                # Copy Experts
                src_ea = src_mql4 / "Experts" / "SmartZonesCollector.mq4"
                dst_ea = target_mql4 / "Experts" / "SmartZonesCollector.mq4"
                if src_ea.exists():
                    shutil.copy2(src_ea, dst_ea)
                
                # Copy Indicators
                src_ind = src_mql4 / "Indicators" / "StrongZones.mq4"
                dst_ind = target_mql4 / "Indicators" / "StrongZones.mq4"
                if src_ind.exists():
                    shutil.copy2(src_ind, dst_ind)
                    
                success_count += 1
                
        if success_count > 0:
            messagebox.showinfo("Success", f"Successfully patched {success_count} MetaTrader 4 terminal(s)!\n\nPlease restart your MT4 terminals and attach the Expert Advisor to chart.")
            self.destroy()
        else:
            messagebox.showwarning("Warning", "No terminals were selected or successfully patched.")

if __name__ == "__main__":
    app = InstallerGUI()
    app.mainloop()
