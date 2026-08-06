import streamlit as st

BASE_BACKGROUND = "#f5f7fb"
CARD_BACKGROUND = "#ffffff"
CARD_BORDER = "1px solid rgba(15, 23, 42, 0.08)"
SHADOW = "0 14px 35px rgba(15, 23, 42, 0.07)"
PRIMARY_COLOR = "#0c4a6e"
SECONDARY_COLOR = "#0ea5e9"
SUCCESS_COLOR = "#16a34a"
WARNING_COLOR = "#f97316"
DANGER_COLOR = "#dc2626"
INFO_COLOR = "#2563eb"
TEXT_COLOR = "#0f172a"
MUTED_COLOR = "#475569"
BORDER_RADIUS = "16px"


def inject_styles():
    st.markdown(
        f"""
        <style>
        :root {{
            color-scheme: light;
            font-family: 'Inter', 'Segoe UI', sans-serif;
        }}
        .streamlit-expanderHeader {{
            font-weight: 600 !important;
        }}
        .stApp {{
            background: {BASE_BACKGROUND};
        }}
        .css-1lcbmhc.e1fqkh3o2 {{
            background: {BASE_BACKGROUND};
        }}
        .main .block-container {{
            padding-top: 1.5rem;
            padding-left: 1.5rem;
            padding-right: 1.5rem;
            padding-bottom: 1.5rem;
            background-color: transparent;
        }}
        .sidebar .sidebar-content {{
            padding-top: 1.2rem;
        }}
        .brand-box {{
            background: linear-gradient(145deg, rgba(14,165,233,0.15), rgba(12,74,110,0.10));
            border: {CARD_BORDER};
            border-radius: {BORDER_RADIUS};
            padding: 1rem 1rem 1rem 1rem;
            margin-bottom: 1rem;
            color: {TEXT_COLOR};
        }}
        .brand-title {{
            font-size: 1rem;
            font-weight: 700;
            line-height: 1.35;
            margin-bottom: 0.25rem;
        }}
        .brand-subtitle {{
            font-size: 0.9rem;
            color: {MUTED_COLOR};
            line-height: 1.5;
        }}
        .sidebar-group-title {{
            margin-top: 1rem;
            margin-bottom: 0.4rem;
            font-size: 0.85rem;
            font-weight: 700;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: {PRIMARY_COLOR};
        }}
        .page-header-box {{
            padding: 1.25rem 1.4rem;
            background: {CARD_BACKGROUND};
            border: {CARD_BORDER};
            border-radius: {BORDER_RADIUS};
            box-shadow: {SHADOW};
            margin-bottom: 1.5rem;
        }}
        .page-title {{
            font-size: 1.85rem;
            font-weight: 700;
            margin-bottom: 0.35rem;
            color: {TEXT_COLOR};
        }}
        .page-description {{
            font-size: 0.98rem;
            color: {MUTED_COLOR};
            line-height: 1.7;
        }}
        .metric-card {{
            padding: 1.25rem;
            border-radius: {BORDER_RADIUS};
            border: {CARD_BORDER};
            background: {CARD_BACKGROUND};
            box-shadow: {SHADOW};
            margin-bottom: 1rem;
        }}
        .metric-title {{
            color: {MUTED_COLOR};
            font-size: 0.92rem;
            margin-bottom: 0.75rem;
            letter-spacing: 0.01em;
        }}
        .metric-value {{
            font-size: 1.9rem;
            font-weight: 700;
            color: {TEXT_COLOR};
            margin-bottom: 0.65rem;
        }}
        .metric-extra {{
            display: flex;
            justify-content: space-between;
            gap: 0.6rem;
            flex-wrap: wrap;
            align-items: center;
            font-size: 0.9rem;
            color: {MUTED_COLOR};
        }}
        .metric-delta {{
            font-weight: 700;
        }}
        .delta-positive {{
            color: {SUCCESS_COLOR};
        }}
        .delta-negative {{
            color: {DANGER_COLOR};
        }}
        .section-box {{
            background: {CARD_BACKGROUND};
            border: {CARD_BORDER};
            border-radius: {BORDER_RADIUS};
            box-shadow: {SHADOW};
            padding: 1.25rem;
            margin-bottom: 1.5rem;
        }}
        .section-title {{
            font-size: 1.1rem;
            font-weight: 700;
            margin-bottom: 1rem;
            color: {TEXT_COLOR};
        }}
        .status-badge {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.35rem 0.75rem;
            border-radius: 999px;
            font-size: 0.8rem;
            font-weight: 700;
            letter-spacing: 0.01em;
            color: #fff;
        }}
        .status-approved {{background: {SUCCESS_COLOR};}}
        .status-pending {{background: {INFO_COLOR};}}
        .status-partial {{background: {WARNING_COLOR};}}
        .status-paid {{background: {SUCCESS_COLOR};}}
        .status-overdue {{background: {DANGER_COLOR};}}
        .status-cancelled {{background: #475569;}}
        .status-completed {{background: {SUCCESS_COLOR};}}
        .status-alert {{background: {WARNING_COLOR};}}
        .status-option {{background: #4338ca;}}
        .status-no-show {{background: #991b1b;}}
        .empty-state {{
            border-radius: {BORDER_RADIUS};
            border: {CARD_BORDER};
            background: {CARD_BACKGROUND};
            padding: 1.4rem;
            box-shadow: {SHADOW};
            margin-bottom: 1.5rem;
        }}
        .empty-state-title {{
            font-size: 1.2rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
            color: {TEXT_COLOR};
        }}
        .empty-state-text {{
            color: {MUTED_COLOR};
            line-height: 1.7;
            margin-bottom: 1rem;
        }}
        .empty-state-button {{
            display: inline-block;
            padding: 0.85rem 1.25rem;
            border-radius: 999px;
            background: {SECONDARY_COLOR};
            color: #fff;
            text-decoration: none;
            font-weight: 700;
        }}
        .quick-action-card {{
            display: block;
            padding: 1.1rem 1rem;
            border-radius: 18px;
            border: {CARD_BORDER};
            background: {CARD_BACKGROUND};
            box-shadow: {SHADOW};
            color: {TEXT_COLOR};
            text-decoration: none;
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }}
        .quick-action-card:hover {{
            transform: translateY(-2px);
            box-shadow: 0 22px 45px rgba(15, 23, 42, 0.10);
        }}
        .quick-action-icon {{
            font-size: 1.45rem;
            margin-bottom: 0.75rem;
        }}
        .quick-action-title {{
            font-size: 1rem;
            font-weight: 700;
            margin-bottom: 0.35rem;
        }}
        .quick-action-help {{
            font-size: 0.92rem;
            color: {MUTED_COLOR};
            line-height: 1.5;
        }}
        .action-button {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            padding: 0.95rem 1.1rem;
            border-radius: 14px;
            background: {SECONDARY_COLOR};
            color: #fff;
            font-weight: 700;
            text-decoration: none;
            text-align: center;
            transition: background 0.2s ease;
        }}
        .action-button:hover {{
            background: #0b82c6;
        }}
        .table-container {{
            overflow-x: auto;
            margin-top: 1rem;
        }}
        .table-container table {{
            width: 100%;
            border-collapse: collapse;
        }}
        .table-container th, .table-container td {{
            padding: 0.9rem 0.85rem;
            text-align: left;
            border-bottom: 1px solid rgba(15, 23, 42, 0.08);
        }}
        .table-container th {{
            color: {PRIMARY_COLOR};
            font-weight: 700;
            background: rgba(14,165,233,0.08);
        }}
        .table-container tr:nth-child(even) {{
            background: rgba(15, 23, 42, 0.02);
        }}
        .table-container td.amount {{
            text-align: right;
            white-space: nowrap;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def format_currency(amount, currency="TRY"):
    try:
        value = float(amount or 0)
    except Exception:
        value = 0.0
    if currency == "TRY":
        text = f"₺{value:,.2f}"
    elif currency == "EUR":
        text = f"€{value:,.2f}"
    elif currency == "USD":
        text = f"${value:,.2f}"
    else:
        text = f"{value:,.2f} {currency}"
    text = text.replace(",", "_").replace(".", ",").replace("_", ".")
    if value < 0:
        text = f"-{text.replace('-', '')}"
    return text


def format_date(value):
    try:
        return value.strftime("%d.%m.%Y")
    except Exception:
        return str(value)


def sidebar_brand():
    st.sidebar.markdown(
        """
        <div class='brand-box'>
            <div class='brand-title'>Seyahat Acentası Finans ve Operasyon</div>
            <div class='brand-subtitle'>Rezervasyon, gelir-gider, tahsilat ve kârlılık yönetimi</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def sidebar_menu(menu_groups):
    default_page = menu_groups[0][1][0]
    st.session_state.setdefault("active_page", default_page)
    valid_pages = {option for _, options in menu_groups for option in options}
    if st.session_state.active_page not in valid_pages:
        st.session_state.active_page = default_page

    for group_title, options in menu_groups:
        st.sidebar.markdown(f"<div class='sidebar-group-title'>{group_title}</div>", unsafe_allow_html=True)
        for option in options:
            active = option == st.session_state.active_page
            if st.sidebar.button(
                f"{'●' if active else '○'} {option}",
                key=f"sidebar_page_{option}",
                type="primary" if active else "secondary",
                width="stretch",
            ):
                st.session_state.active_page = option
                st.rerun()

    return st.session_state.active_page


def _navigate_to(page):
    st.session_state.active_page = page
    st.rerun()


def render_quick_action_cards(actions, columns=3):
    cols = st.columns(columns, gap="large")
    for index, action in enumerate(actions):
        with cols[index % columns]:
            if st.button(
                f"{action.get('icon', '⚡')} {action['label']}",
                key=f"quick_action_{action['page']}_{index}",
                help=action.get("help", ""),
                width="stretch",
            ):
                _navigate_to(action["page"])


def action_button(label, page=None, icon=None):
    if page:
        if st.button(
            f"{icon or '➕'} {label}",
            key=f"page_action_{page}_{label}",
            type="primary",
            width="stretch",
        ):
            _navigate_to(page)
    else:
        return st.button(label)


def page_header(title, subtitle, action_label=None, action_page=None):
    cols = st.columns([4, 1], gap="large")
    with cols[0]:
        st.markdown(
            f"""
            <div class='page-header-box'>
                <div class='page-title'>{title}</div>
                <div class='page-description'>{subtitle}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with cols[1]:
        if action_label and action_page:
            action_button(action_label, page=action_page, icon="➕")
    return None


def section_header(title, description=None):
    st.markdown(
        f"""
        <div class='section-box'>
            <div class='section-title'>{title}</div>
            {f'<div class="page-description">{description}</div>' if description else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_cards(metrics, columns=4):
    cols = st.columns(columns, gap="large")
    for index, metric in enumerate(metrics):
        with cols[index % columns]:
            delta_class = "delta-positive" if metric.get("delta", "") and metric.get("delta", "").startswith("+") else "delta-negative"
            delta_text = metric.get("delta", "")
            icon = metric.get("icon", "")
            note = metric.get("note", "")
            st.markdown(
                f"""
                <div class='metric-card'>
                    <div class='metric-title'>{metric['title']}</div>
                    <div class='metric-value'>{metric['value']}</div>
                    <div class='metric-extra'>
                        <div class='metric-note'>{note}</div>
                        <div class='metric-delta {delta_class}'>{delta_text}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def status_badge(label):
    slug = label.lower().replace(" ", "-")
    mapping = {
        "onaylandı": "approved",
        "beklemede": "pending",
        "kısmen ödendi": "partial",
        "tam ödendi": "paid",
        "vadesi geçti": "overdue",
        "iptal edildi": "cancelled",
        "tamamlandı": "completed",
        "sorunlu": "alert",
        "opsiyon": "option",
        "no-show": "no-show",
    }
    css = mapping.get(slug, "pending")
    return f"<span class='status-badge status-{css}'>{label}</span>"


def empty_state(title, text, button_label=None, button_key=None):
    button_clicked = False
    st.markdown(
        f"""
        <div class='empty-state'>
            <div class='empty-state-title'>{title}</div>
            <div class='empty-state-text'>{text}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if button_label:
        button_clicked = st.button(button_label, key=button_key or title)
    return button_clicked
