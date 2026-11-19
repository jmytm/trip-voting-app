"""Shared, restrained chart styling for the voting layouts and results."""
import html

import altair as alt

PALETTE = ['#94B9D5', '#DDA984', '#93BCAD', '#B6A6CE',
           '#B6BECC', '#C8B78F', '#C5A7AF', '#A9BBA1']
TEXT = '#374151'
SECONDARY = '#737B86'
BORDER = '#DFE3E8'
UNALLOCATED = '#E5E7EB'


def item_colors(names):
    # Use the complete option list, so rank or allocation changes don't recolor items.
    return {name: PALETTE[index % len(PALETTE)]
            for index, name in enumerate(sorted(set(names)))}


def color_scale(colors):
    return alt.Scale(domain=list(colors), range=list(colors.values()))


def chart_style(chart):
    return (chart.configure(background='transparent')
            .configure_view(stroke=None)
            .configure_axis(grid=False, labelColor=SECONDARY, titleColor=TEXT,
                            domainColor=BORDER, tickColor=BORDER, titleFontWeight='normal')
            .configure_legend(labelColor=TEXT, titleColor=TEXT, titleFontWeight='normal'))


def distribution_legend(segments, colors):
    entries = []
    for segment in segments:
        name = html.escape(segment['item'])
        color = colors[segment['item']]
        entries.append(
            f'<span style="display:inline-flex;align-items:center;gap:6px;">'
            f'<span aria-hidden="true" style="width:10px;height:10px;border-radius:2px;background:{color};"></span>'
            f'{name} <span style="color:{SECONDARY}">{segment["tokens"]} tokens · {segment["percentage"]:.1%}</span></span>')
    return ('<div style="display:flex;flex-wrap:wrap;gap:8px 18px;font-size:0.875rem;'
            f'color:{TEXT};margin:4px 0 12px;">' + ''.join(entries) + '</div>')
