"""Stub package per il server MCP 'api_to_mcp'.

Generato automaticamente da scripts/generate_tool_files.py.
Importa e ri-esporta tutti i tool del server.
"""
from .get_status import get_status
from .cities_index import cities_index
from .events_categories_get import events_categories_get
from .thems_get import thems_get
from .target_get import target_get
from .languages_get import languages_get
from .localities_get import localities_get
from .iat_get import iat_get
from .events_get import events_get
from .news_get import news_get
from .interests_get import interests_get
from .itineraries_get import itineraries_get
from .poi_list_get import poi_list_get
from .poi_single_get import poi_single_get
from .images_get import images_get
from .webcam_get import webcam_get

__all__ = ['get_status', 'cities_index', 'events_categories_get', 'thems_get', 'target_get', 'languages_get', 'localities_get', 'iat_get', 'events_get', 'news_get', 'interests_get', 'itineraries_get', 'poi_list_get', 'poi_single_get', 'images_get', 'webcam_get']
