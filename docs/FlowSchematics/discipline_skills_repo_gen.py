import math

cycles = ["TY2025", "2026 Q1", "2026 Q2", "2026 Q3", "2026 Q4", "TY2026"]
n = len(cycles)

card_w = 820
card_h = 560
gap = 70
margin_x = 40
margin_top = 30
margin_bottom = 30

total_w = card_w + 2*margin_x
total_h = margin_top + n*card_h + (n-1)*gap + margin_bottom

# per-card triangle geometry (relative to card top-left)
pad_top = 70      # room for cycle title
pad_side = 70
pad_bottom = 70

apex = (card_w/2, pad_top)
left = (pad_side, card_h - pad_bottom)
right = (card_w - pad_side, card_h - pad_bottom)

def angle_deg(p1, p2):
    dx = p2[0]-p1[0]
    dy = p2[1]-p1[1]
    return math.degrees(math.atan2(dy, dx))

ang_left = angle_deg(left, apex)    # AppDev -> AcctOps
ang_right = angle_deg(apex, right)  # AcctOps -> DevOps

mid_left = ((apex[0]+left[0])/2, (apex[1]+left[1])/2)
mid_right = ((apex[0]+right[0])/2, (apex[1]+right[1])/2)
mid_base = ((left[0]+right[0])/2, left[1])

# blue shade per cycle, darkening down the stack
blues = ["#5b8def", "#3f72d4", "#2f5cc0", "#244aa3", "#1a3a86", "#102a69"]

parts = []
parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total_w} {total_h}" width="100%" style="background:#ffffff;font-family:Helvetica,Arial,sans-serif;">')

# arrow marker defs (one per stroke color, simplified to single dark marker)
parts.append('''<defs>
  <marker id="arrowhead" markerWidth="10" markerHeight="10" refX="6" refY="5" orient="auto">
    <path d="M0,0 L10,5 L0,10 z" fill="#444444"/>
  </marker>
</defs>''')

for i, label in enumerate(cycles):
    oy = margin_top + i*(card_h+gap)
    ox = margin_x
    stroke = blues[i % len(blues)]
    sw = 3 + (i*0.3)

    cx = lambda x: ox + x
    cy = lambda y: oy + y

    a = (cx(apex[0]), cy(apex[1]))
    l = (cx(left[0]), cy(left[1]))
    r = (cx(right[0]), cy(right[1]))
    ml = (cx(mid_left[0]), cy(mid_left[1]))
    mr = (cx(mid_right[0]), cy(mid_right[1]))
    mb = (cx(mid_base[0]), cy(mid_base[1]))

    parts.append(f'<g>')
    # card border (cascading box)
    parts.append(f'<rect x="{ox}" y="{oy}" width="{card_w}" height="{card_h}" rx="14" '
                 f'fill="none" stroke="#94a3b8" stroke-width="1.5" stroke-dasharray="6,4"/>')
    # cycle title
    parts.append(f'<text x="{ox+20}" y="{oy+34}" font-size="20" font-weight="700" fill="#334155">Cycle: {label}</text>')

    # triangle edges
    parts.append(f'<line x1="{l[0]:.1f}" y1="{l[1]:.1f}" x2="{a[0]:.1f}" y2="{a[1]:.1f}" stroke="{stroke}" stroke-width="{sw:.1f}"/>')
    parts.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{r[0]:.1f}" y2="{r[1]:.1f}" stroke="{stroke}" stroke-width="{sw:.1f}"/>')
    parts.append(f'<line x1="{l[0]:.1f}" y1="{l[1]:.1f}" x2="{r[0]:.1f}" y2="{r[1]:.1f}" stroke="{stroke}" stroke-width="{sw:.1f}"/>')

    # vertex labels
    parts.append(f'<text x="{a[0]:.1f}" y="{a[1]-16:.1f}" font-size="22" font-weight="700" text-anchor="middle" fill="#111111">AcctOps</text>')
    parts.append(f'<text x="{l[0]-16:.1f}" y="{l[1]+6:.1f}" font-size="22" font-weight="700" text-anchor="end" fill="#111111">AppDev</text>')
    parts.append(f'<text x="{r[0]+16:.1f}" y="{r[1]+6:.1f}" font-size="22" font-weight="700" text-anchor="start" fill="#111111">DevOps</text>')

    # edge labels (rotated along the slant)
    parts.append(f'<text x="{ml[0]:.1f}" y="{ml[1]:.1f}" font-size="17" fill="#222222" text-anchor="middle" '
                 f'transform="rotate({ang_left:.2f} {ml[0]:.1f} {ml[1]:.1f})" dy="-10">Session / Repos</text>')
    parts.append(f'<text x="{mr[0]:.1f}" y="{mr[1]:.1f}" font-size="17" fill="#222222" text-anchor="middle" '
                 f'transform="rotate({ang_right:.2f} {mr[0]:.1f} {mr[1]:.1f})" dy="-10">Agents (Skills, Knowledge)</text>')
    parts.append(f'<text x="{mb[0]:.1f}" y="{mb[1]+26:.1f}" font-size="17" fill="#222222" text-anchor="middle">Projects (Milestones)</text>')

    parts.append('</g>')

    # cascade connector to next cycle
    if i < n-1:
        y1 = oy + card_h
        y2 = oy + card_h + gap
        xmid = ox + card_w/2
        parts.append(f'<line x1="{xmid:.1f}" y1="{y1:.1f}" x2="{xmid:.1f}" y2="{y2-6:.1f}" stroke="#444444" '
                     f'stroke-width="2" marker-end="url(#arrowhead)"/>')
        parts.append(f'<text x="{xmid+14:.1f}" y="{(y1+y2)/2:.1f}" font-size="14" fill="#444444">YE Close → Next Cycle Setup</text>')

parts.append('</svg>')

svg = "\n".join(parts)
with open('/tmp/discipline_skills_repo.svg', 'w') as f:
    f.write(svg)
print("written", len(svg), "bytes")
print("ang_left", ang_left, "ang_right", ang_right)
