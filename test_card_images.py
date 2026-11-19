import tempfile
import unittest
import ast
import html
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch

import card_images
import db


class CardImageTests(unittest.TestCase):
    def test_first_image_resolves_against_redirected_page(self):
        headers = Message()
        headers['Content-Type'] = 'text/html; charset=utf-8'
        response = MagicMock()
        response.headers = headers
        response.geturl.return_value = 'https://example.com/hotels/details'
        response.read.return_value = b'<img src="../first.jpg"><img src="/second.jpg">'
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = response
        with patch.object(card_images, '_public_page'), patch.object(card_images, 'build_opener', return_value=opener):
            self.assertEqual(card_images.discover_card_image('https://example.com/hotel'),
                             'https://example.com/first.jpg')

    def test_lazy_image_and_no_image(self):
        parser = card_images._Images('https://example.com/')
        parser.feed('<img src="data:image/gif;base64,AA" data-src="/photo.jpg">')
        self.assertEqual(parser.image, 'https://example.com/photo.jpg')
        parser = card_images._Images('https://example.com/')
        parser.feed('<h1>No images</h1>')
        self.assertEqual(parser.image, '')

    def test_fetch_failure_is_optional(self):
        with patch.object(card_images, '_public_page', side_effect=OSError('timeout')):
            self.assertEqual(card_images.discover_card_image('https://example.com/'), '')

    def test_social_preview_takes_priority_over_content_and_twitter(self):
        parser = card_images._Images('https://example.com/hotel/')
        parser.feed('<img src="content.jpg"><meta name="twitter:image" content="/twitter.jpg">'
                    '<meta property="og:image" content="/preview.jpg">')
        self.assertEqual(parser.image, 'https://example.com/preview.jpg')

    def test_twitter_preview_when_open_graph_invalid(self):
        parser = card_images._Images('https://example.com/')
        parser.feed('<meta property="og:image" content="data:image/png;base64,AA">'
                    '<meta name="twitter:image" content="/preview.jpg">')
        self.assertEqual(parser.image, 'https://example.com/preview.jpg')

    def test_skip_logos_icons_and_tiny_images(self):
        parser = card_images._Images('https://example.com/')
        parser.feed('<img src="/brand.png" alt="Website logo">'
                    '<img src="/icon.svg"><img src="/track.gif" width="1" height="1">'
                    '<img src="/content.jpg" width="800" height="600">')
        self.assertEqual(parser.image, 'https://example.com/content.jpg')

    def test_prefer_main_content_over_large_header_image(self):
        parser = card_images._Images('https://example.com/')
        parser.feed('<img src="/header.jpg" width="2000" height="1000">'
                    '<main><img src="/room.jpg" width="800" height="600"></main>')
        self.assertEqual(parser.image, 'https://example.com/room.jpg')

    def test_no_suitable_content_image(self):
        parser = card_images._Images('https://example.com/')
        parser.feed('<img src="/logo.png"><img src="/pixel.gif" width="1">')
        self.assertEqual(parser.image, '')

    def test_logo_social_preview_falls_back_to_content(self):
        parser = card_images._Images('https://example.com/')
        parser.feed('<meta property="og:image" content="/brand-logo.png">'
                    '<meta name="twitter:image" content="/favicon.png">'
                    '<main><img src="/room.jpg" width="800" height="600"></main>')
        self.assertEqual(parser.image, 'https://example.com/room.jpg')

    def test_social_alt_and_size_reject_branding_and_tiny_previews(self):
        parser = card_images._Images('https://example.com/')
        parser.feed('<meta property="og:image" content="/brand.png">'
                    '<meta property="og:image:alt" content="Website logo">'
                    '<meta property="og:image" content="/small.jpg">'
                    '<meta property="og:image:width" content="32">'
                    '<meta property="og:image" content="/room.jpg">')
        self.assertEqual(parser.image, 'https://example.com/room.jpg')

    def test_body_logo_description_rejects_same_social_image(self):
        parser = card_images._Images('https://example.com/')
        parser.feed('<meta property="og:image" content="/brand.png">'
                    '<img src="/brand.png" alt="Company logo"><img src="/hotel.jpg">')
        self.assertEqual(parser.image, 'https://example.com/hotel.jpg')

    def test_preview_keeps_exact_selection_and_invalidates_changed_urls(self):
        # Exercise preview state without fetching external images or touching real votes.
        tree = ast.parse(Path('app.py').read_text(encoding='utf-8'))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'card_preview')
        streamlit = MagicMock()
        streamlit.session_state = {}
        storage = MagicMock()
        storage.discover_card_image.return_value = 'https://example.com/room.jpg'
        namespace = dict(st=streamlit, storage=storage, html=html, validate_card_urls=db.validate_card_urls)
        exec(compile(ast.Module(body=[helper], type_ignores=[]), 'app.py', 'exec'), namespace)
        preview = namespace['card_preview']
        self.assertIsNone(preview('new', '', 'https://example.com/hotel', False))
        self.assertEqual(preview('new', '', 'https://example.com/hotel', True), 'https://example.com/room.jpg')
        self.assertEqual(preview('new', '', 'https://example.com/hotel', False), 'https://example.com/room.jpg')
        self.assertIsNone(preview('new', '', 'https://example.com/other', False))
        storage.discover_card_image.assert_called_once()
        self.assertEqual(preview('new', 'https://example.com/manual.jpg', '', True), 'https://example.com/manual.jpg')
        storage.discover_card_image.return_value = ''
        self.assertEqual(preview('edit_1', '', 'https://example.com/empty', True), '')

    def test_local_addresses_are_not_fetched(self):
        with patch.object(card_images.socket, 'getaddrinfo', return_value=[(None, None, None, None, ('127.0.0.1', 80))]):
            with self.assertRaises(ValueError):
                card_images._public_page('http://localhost/')

    def test_save_discovers_only_when_image_blank(self):
        previous = db.DB_PATH
        with tempfile.NamedTemporaryFile(dir=Path.cwd(), suffix='.db', delete=False) as handle:
            db.DB_PATH = Path(handle.name)
        try:
            db.initialize()
            with db.connect() as conn:
                conn.execute("INSERT INTO destinations(name,min_tokens,max_tokens) VALUES ('Hotel',10,50)")
            with patch.object(db, 'discover_card_image', return_value='https://example.com/auto.jpg') as discover:
                db.save_card_details(1, '', 'https://example.com/hotel')
                self.assertEqual(db.rows('SELECT image_url FROM destinations')[0]['image_url'], 'https://example.com/auto.jpg')
                discover.assert_called_once()
                discover.reset_mock()
                db.save_card_details(1, 'https://example.com/manual.jpg', 'https://example.com/hotel')
                discover.assert_not_called()
                db.save_card_details(1, '', 'https://example.com/hotel', auto_discover=False)
                discover.assert_not_called()
                self.assertEqual(db.rows('SELECT image_url FROM destinations')[0]['image_url'], '')
        finally:
            db.DB_PATH.unlink(missing_ok=True)
            db.DB_PATH = previous


if __name__ == '__main__':
    unittest.main()
