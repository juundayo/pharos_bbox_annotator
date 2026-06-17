# Bounding Box & Reading Order Annotation App

A lightweight interactive tool for creating and editing bounding boxes and assigning reading order on document images. Designed for fast annotation and intuitive navigation.

---

## Features

- Create, edit, and refine bounding boxes directly on the image.
- Assign reading order visually.
- Hide or isolate bounding boxes for focused editing.
- Navigate documents and pages through a sidebar interface.
- Edit metadata (category, order) through a dedicated panel.

---

## Keyboard Shortcuts

### Navigation
- **W / A / S / D** — Pan the image

### Bounding Box Operations
- **Q** — Add a new bounding box  
- **E** — Edit an existing bounding box (category, reading order)

### Reading Order
- **O** — Open the reading‑order editor (click elements in the desired sequence)

### View Control
- **Click on a bounding box** — Isolate it; all others are hidden  
  - Drag edges or corners to resize  
  - Use the **(+)** handle to add additional points  
- **Esc** — Return to the full bounding‑box view

---

## Interface Overview

### Right Panel
- Displays all bounding boxes in their current reading order  
- Allows:
  - Reordering (arrow keys)
  - Editing metadata
  - Deleting boxes

### Left Panel
- Lists all documents and their corresponding pages  
- Enables quick switching between files

---

## Usage

Run the application in one of two ways:

### 1. Interactive Mode

```bash
python bbox_editor.py
```

Opens the document selection menu and allows browsing all available PDFs and their rendered images.

### 2. Direct File Mode
```bash
python bbox_editor.py --image IMG_PATH --bbox_res BBOX_RES_TXT_PATH --bbox_gt BBOX_GT_TXT_PATH
```

- Loads the specified image and bounding‑box files directly

- Skips the document selection menu

- Useful for scripting or working on a single file
