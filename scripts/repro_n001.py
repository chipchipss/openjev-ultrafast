import sys
sys.path.insert(0, '.')
from jev_ultrafast import skills
from urllib.parse import urlparse

# why does python.org/doc/ still fire? Trace C2b on the intermediate page:
goal = "Open the Python documentation section from the top navigation."
page_mid = {"url": "https://www.python.org/doc/", "title": "3.10.12 Documentation",
            "text": "Python documentation", "start_url": "https://www.python.org/", "actions": []}
start_flat = skills._flat(skills._norm_page("https://www.python.org/"))
print("start flat:", repr(start_flat))
print("'doc' in start flat?", "doc" in start_flat)  # 'python.org' contains no 'doc'... wait
# 'doc' IS a substring of nothing here... but flat is 'https www python org'
# hmm 'doc' not in it. So my guard 'k not in start' does NOT exclude 'doc'.
# Then C2b matched 'doc' in here_url 'python org doc'.
# The real distinction: docs.python.org has 'docs' in the HOST; /doc/ is a PATH on
# the starting site. C1's original warning was about the START site's own /doc/ page.
# Correct guard: expansions may only match in the HOST, never in the path.
u = urlparse("https://www.python.org/doc/")
host_flat = skills._flat(skills._norm_page(u.netloc))
print("host flat:", repr(host_flat), "| 'docs' in host?", "docs" in host_flat, "| 'doc' in host?", "doc" in host_flat)
u2 = urlparse("https://docs.python.org/3/")
host2 = skills._flat(skills._norm_page(u2.netloc))
print("target host flat:", repr(host2), "| 'docs' in host?", "docs" in host2)
