# SPDX-License-Identifier: GPL-3.0-or-later
"""Feuille de style Qt générée à partir des jetons."""
from __future__ import annotations

from montar.ui.theme.tokens import (
    FONT_MONO,
    FONT_UI,
    RADIUS_CARD,
    RADIUS_CLIP,
    RADIUS_CONTROL,
    RADIUS_WINDOW,
    Palette,
)

_TEMPLATE = """
* {{ font-family: "{font}"; }}
QWidget {{ color: {ink}; font-size: 14px; }}
QMainWindow, QDialog, #Page {{ background: {background}; }}
QToolTip {{ background: {ink}; color: {background}; border: none; padding: 4px 8px;
           border-radius: 6px; }}

/* --- textes ------------------------------------------------------------ */
QLabel {{ background: transparent; }}
QLabel[role="h1"] {{ font-size: 30px; font-weight: 800; }}
QLabel[role="h2"] {{ font-size: 20px; font-weight: 700; }}
QLabel[role="h3"] {{ font-size: 16px; font-weight: 700; }}
QLabel[role="muted"] {{ color: {text_muted}; }}
QLabel[role="small"] {{ color: {text_muted}; font-size: 12px; }}
QLabel[role="section"] {{ color: {text_muted}; font-size: 12px; font-weight: 700;
                         letter-spacing: 1px; }}
QLabel[role="mono"], QLineEdit[role="mono"] {{ font-family: "{mono}"; }}
QLabel[role="logo"] {{ font-size: 22px; font-weight: 800; }}
QLabel[role="badge"] {{ background: {badge_bg}; color: #FFFFFF; font-family: "{mono}";
                       font-size: 11px; border-radius: 4px; padding: 1px 5px; }}

/* --- boutons ----------------------------------------------------------- */
QPushButton, QToolButton {{
    background: {surface}; border: 1px solid {border}; border-radius: {r_control}px;
    padding: 8px 16px; font-weight: 600; color: {ink};
}}
QPushButton:hover, QToolButton:hover {{ background: {mist}; }}
QPushButton:disabled, QToolButton:disabled {{ color: {text_muted}; background: transparent; }}
QPushButton[variant="primary"] {{ background: {forest}; border-color: {forest};
                                  color: {on_forest}; }}
QPushButton[variant="primary"]:hover {{ background: {forest_hover}; }}
QPushButton[variant="primary"]:disabled {{ background: {mist}; border-color: {mist};
                                           color: {text_muted}; }}
QPushButton[variant="secondary"] {{ color: {forest}; }}
QPushButton[variant="tonal"] {{ background: {mist}; border-color: {mist}; color: {forest}; }}
QPushButton[variant="tonal"]:hover {{ background: {sage}; }}
QPushButton[variant="dashed"] {{ background: {field}; border: 1.5px dashed {sage};
                                 color: {forest}; padding: 12px; }}
QPushButton[variant="ghost"], QToolButton[variant="ghost"] {{
    background: transparent; border: none; padding: 6px; }}
QPushButton[variant="ghost"]:hover, QToolButton[variant="ghost"]:hover {{ background: {mist}; }}
QPushButton[variant="toggle"] {{ background: transparent; border: none; padding: 6px; }}
QPushButton[variant="toggle"]:hover {{ background: {mist}; }}
QPushButton[variant="toggle"]:checked {{ background: {mist}; }}
QPushButton[variant="link"] {{ background: transparent; border: none; padding: 2px;
                               color: {forest}; text-decoration: underline; }}
QPushButton[variant="round"] {{ background: {forest}; border: none; border-radius: 23px;
                                min-width: 46px; max-width: 46px; min-height: 46px;
                                max-height: 46px; padding: 0; }}
QPushButton[variant="round"]:hover {{ background: {forest_hover}; }}
QPushButton[variant="chip"] {{ border-radius: 16px; padding: 5px 14px; font-weight: 500; }}
QPushButton::menu-indicator {{ image: none; width: 0; }}
QPushButton[variant="chip"][compact="true"] {{ padding: 4px 10px; font-size: 13px;
                                                  border-radius: 14px; }}
QPushButton[variant="chip"]:checked {{ background: {ink}; border-color: {ink};
                                       color: {background}; }}

/* navigation latérale de l'accueil */
QPushButton[variant="nav"] {{ background: transparent; border: none; text-align: left;
                              padding: 10px 14px; font-weight: 500; border-radius: 10px; }}
QPushButton[variant="nav"]:hover {{ background: {mist}; }}
QPushButton[variant="nav"]:checked {{ background: {mist}; font-weight: 700; }}

/* rail vertical de l'éditeur */
QToolButton[variant="rail"] {{ background: transparent; border: none; border-radius: 12px;
                               padding: 6px 2px; font-size: 12px; font-weight: 500;
                               min-width: 64px; }}
QToolButton[variant="rail"]:hover {{ background: {mist}; }}
QToolButton[variant="rail"]:checked {{ background: {mist}; color: {forest}; font-weight: 700; }}

/* contrôle segmenté */
#Segmented {{ background: {segmented_bg}; border-radius: {r_control}px; }}
#Segmented QPushButton {{ background: transparent; border: none; padding: 7px 16px;
                          border-radius: 8px; font-weight: 500; color: {ink}; }}
#Segmented QPushButton:checked {{ background: {surface}; font-weight: 700; }}
#Segmented[compact="true"] QPushButton {{ padding: 6px 8px; font-size: 13px; }}
#Inspector QPushButton[variant="secondary"] {{ padding: 6px 8px; }}
#Inspector QLineEdit, #Inspector QComboBox, #Inspector QSpinBox,
#Inspector QPlainTextEdit {{ padding: 5px 8px; }}
QPlainTextEdit {{ background: {field}; border: 1px solid {border};
                  border-radius: {r_control}px; padding: 6px; }}
#Segmented QPushButton:disabled {{ color: {text_muted}; }}

/* tuiles et cartes */
#Card, QFrame[card="true"] {{ background: {surface}; border: 1px solid {border};
                              border-radius: {r_card}px; }}
QPushButton[variant="tile"] {{ background: {surface}; border: 1px solid {border};
                               border-radius: {r_card}px; text-align: left; padding: 0; }}
QPushButton[variant="tile"]:hover {{ border-color: {sage}; }}
QPushButton[variant="tile"]:checked {{ border: 2px solid {forest}; }}
QPushButton[variant="tile-primary"] {{ background: {forest}; border: none;
                                       border-radius: {r_card}px; padding: 0; }}
QPushButton[variant="tile-primary"]:hover {{ background: {forest_hover}; }}
QPushButton[variant="tile-primary"] QLabel {{ color: {on_forest}; }}

/* --- champs ------------------------------------------------------------ */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: {field}; border: 1px solid {border}; border-radius: {r_control}px;
    padding: 8px 12px; selection-background-color: {sage};
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {forest}; }}
QLineEdit[variant="search"] {{ background: {surface}; padding-left: 36px;
                               border-radius: 12px; }}
QLineEdit[variant="title"] {{ background: transparent; border: 1px solid transparent;
                              font-weight: 700; font-size: 16px; padding: 2px 4px; }}
QLineEdit[variant="title"]:hover {{ border-color: {border}; }}
QLineEdit[variant="title"]:focus {{ border-color: {forest}; background: {field}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border};
                               selection-background-color: {mist}; selection-color: {ink}; }}

QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {forest}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {forest}; width: 16px; height: 16px;
                              margin: -6px 0; border-radius: 8px;
                              border: 2px solid {surface}; }}

QCheckBox {{ spacing: 8px; }}

/* --- listes ------------------------------------------------------------ */
QListView, QListWidget {{ background: transparent; border: none; outline: none; }}
QListView::item {{ border-radius: {r_clip}px; color: {ink}; }}
QListView::item:hover {{ background: {mist}; }}
QListView::item:selected {{ background: {mist}; color: {ink}; }}

QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {sage}; border-radius: 3px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {sage}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* --- structure --------------------------------------------------------- */
#Sidebar {{ background: {sidebar}; border-right: 1px solid {border}; }}
#EditorHeader {{ background: {surface}; border-bottom: 1px solid {border}; }}
#Rail {{ background: {sidebar}; border-right: 1px solid {border}; }}
#SidePanel {{ background: {surface}; border-right: 1px solid {border}; }}
#TimelinePanel {{ background: {surface}; border-top: 1px solid {border}; }}
#TimelineBar {{ background: {surface}; border-bottom: 1px solid {border}; }}
#Inspector {{ background: {surface}; border-left: 1px solid {border}; }}
#PreviewArea {{ background: {field}; }}
#PreviewFrame {{ background: {preview_bg}; border-radius: {r_card}px; }}
#DialogCard {{ background: {surface}; border-radius: {r_window}px; }}
#DialogFooter {{ border-top: 1px solid {border}; }}
#InfoBox {{ background: {mist}; border-radius: 12px; }}
#LogoMark {{ background: {forest}; border-radius: 10px; }}
#Avatar {{ background: {mint}; color: {forest}; border-radius: 22px; font-weight: 700; }}
#ThumbPlaceholder {{ background: {mint}; border-radius: {r_card}px; }}
#EmptyState {{ background: {surface}; border: 1.5px dashed {border};
               border-radius: {r_card}px; }}
QSplitter::handle {{ background: {border}; }}
#Separator {{ background: {border}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {mist}; }}
QMessageBox {{ background: {surface}; }}
"""


def _shade(hex_color: str, factor: float) -> str:
    """Assombrit (factor < 1) ou éclaircit (factor > 1) une couleur #RRGGBB."""
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    if factor < 1:
        r, g, b = (int(c * factor) for c in (r, g, b))
    else:
        r, g, b = (int(c + (255 - c) * (factor - 1)) for c in (r, g, b))
    return f"#{r:02X}{g:02X}{b:02X}"


def build_stylesheet(p: Palette) -> str:
    return _TEMPLATE.format(
        font=FONT_UI,
        mono=FONT_MONO,
        r_clip=RADIUS_CLIP,
        r_control=RADIUS_CONTROL,
        r_card=RADIUS_CARD,
        r_window=RADIUS_WINDOW,
        forest_hover=_shade(p.forest, 1.12 if p.dark else 0.88),
        segmented_bg=p.mist if not p.dark else p.field,
        badge_bg="#17261E" if not p.dark else "#0A120E",
        **{k: v for k, v in vars(p).items() if k != "dark"},
    )
