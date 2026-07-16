from weasyprint import HTML
import logging
logging.getLogger("weasyprint").setLevel(logging.ERROR)

html_str = """
<html><body>
<table>
    <tr><td>Row 1</td><td class="fill-amount"></td><td class="fill-date"></td></tr>
    <tr><td>Row 2</td><td class="fill-amount"></td><td class="fill-date"></td></tr>
</table>
</body></html>
"""
doc = HTML(string=html_str).render()
for i, page in enumerate(doc.pages):
    # Traverse the tree
    def traverse(box):
        if getattr(box, 'element_tag', None) == 'td':
            # Check attributes? Weasyprint boxes might not have attributes directly.
            # But we can check box.element_tag
            pass
        # In newer Weasyprint, we can use box.bookmark or box.element_tag
        if hasattr(box, 'children') and box.children:
            for child in box.children:
                traverse(child)
    
    traverse(page._page_box)
print("Rendered.")
