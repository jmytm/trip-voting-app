"""Shared, restrained chart styling for the voting layouts and results."""
import html

import altair as alt
import pandas as pd

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


def distribution_chart(segments, colors, value_title='Tokens', value_format='.0f'):
    data = []
    offset = 0.0
    extent = max(1, sum(s['percentage'] for s in segments))
    for segment in segments:
        row = dict(segment)
        row['start'] = offset
        offset += row['percentage']
        row['end'] = offset
        row['midpoint'] = (row['start'] + row['end']) / 2
        row['label'] = format(row['tokens'], value_format)
        row['show_label'] = row['percentage'] / extent >= max(0.035, len(row['label']) * 0.009)
        data.append(row)
    base = alt.Chart(pd.DataFrame(data))
    scale = alt.Scale(domain=[0, extent])
    tooltip = [alt.Tooltip('item:N', title='Item'),
               alt.Tooltip('tokens:Q', title=value_title, format=value_format),
               alt.Tooltip('percentage:Q', title='Percentage', format='.2%')]
    bar = base.mark_bar(stroke='#FAFAF9', strokeWidth=2).encode(
        x=alt.X('start:Q', title=None, axis=None, scale=scale), x2='end:Q',
        color=alt.Color('item:N', scale=color_scale(colors), legend=None), tooltip=tooltip)
    labels = base.transform_filter(alt.datum.show_label)
    names = labels.mark_text(color='white', fontWeight='bold', fontSize=12, dy=-11,
                             limit=alt.ExprRef(expr=f'max(0, (datum.end - datum.start) / {extent} * width - 10)')).encode(
        x=alt.X('midpoint:Q', scale=scale), text='item:N', tooltip=tooltip)
    counts = labels.mark_text(color='white', fontWeight='bold', fontSize=13, dy=12).encode(
        x=alt.X('midpoint:Q', scale=scale), text='label:N', tooltip=tooltip)
    return chart_style((bar + names + counts).properties(height=104))


def distribution_legend(segments, colors, value_label='tokens', value_format=None):
    entries = []
    for segment in segments:
        name = html.escape(segment['item'])
        color = colors[segment['item']]
        value = format(segment['tokens'], value_format) if value_format else str(segment['tokens'])
        entries.append(
            f'<span style="display:inline-flex;align-items:center;gap:6px;">'
            f'<span aria-hidden="true" style="width:10px;height:10px;border-radius:2px;background:{color};"></span>'
            f'{name} <span style="color:{SECONDARY}">{value} {value_label} · {segment["percentage"]:.1%}</span></span>')
    return ('<div style="display:flex;flex-wrap:wrap;gap:8px 18px;font-size:0.875rem;'
            f'color:{TEXT};margin:4px 0 12px;">' + ''.join(entries) + '</div>')
