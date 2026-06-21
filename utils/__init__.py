# Marks `utils` as a regular package (was an implicit namespace package).
# DO NOT DELETE: without this file, a stray `utils.py` on PYTHONPATH (e.g.
# D:\bushu_binary_model\utils.py, leaked in when another conda env's tool
# launches Finetuning) shadows this package and breaks `from utils.helpers
# import ...` -> the GUI dies silently under pythonw. Keeping this empty file
# makes the package immune to that shadowing.
