"""From the site's JSON to ``sendMessage`` parameters."""
import unittest

from bot import events

PANEL = 'https://graphix.uz/uz/boshqaruv/buyurtmalar/GX-260916-0001/'
TEXT = ('✅ <b>Yangi buyurtma — toʻlandi</b> GX-260916-0001\n'
        '• Mahsulot — M × 1\n\n<b>Jami:</b> 190000 soʻm\n'
        f'\n<a href="{PANEL}">Buyurtmani ochish</a>')


def order(text=TEXT, url=PANEL):
    """An ``order.paid`` body shaped like the contract's example."""
    return {'event': 'order.paid', 'sent_at': '2026-09-16T23:41:07+05:00', 'text': text,
            'parse_mode': 'HTML', 'data': {'order': {'id': 42, 'admin_url': url}}}


class MessageForTests(unittest.TestCase):
    """The text is forwarded as it is, plus a button, minus the line the button replaces."""

    def test_order_gets_a_panel_button_and_loses_the_duplicate_line(self):
        params = events.message_for(order())
        self.assertEqual(params['reply_markup'],
                         {'inline_keyboard': [[{'text': 'Buyurtmani ochish', 'url': PANEL}]]})
        self.assertTrue(params['text'].endswith('190000 soʻm'))
        self.assertNotIn('<a href', params['text'])
        self.assertEqual(params['parse_mode'], 'HTML')
        self.assertTrue(params['disable_web_page_preview'])

    def test_button_labels_follow_the_event(self):
        msg = {'event': 'message.created', 'text': 'x',
               'data': {'message': {'admin_url': 'https://graphix.uz/uz/boshqaruv/xabarlar/#xabar-7'}}}
        self.assertEqual(events.message_for(msg)['reply_markup']['inline_keyboard'][0][0]['text'],
                         'Xabarni ochish')
        rev = {'event': 'review.created', 'text': 'x',
               'data': {'review': {'admin_url': 'https://graphix.uz/uz/boshqaruv/sharhlar/#sharh-3'}}}
        self.assertEqual(events.message_for(rev)['reply_markup']['inline_keyboard'][0][0]['text'],
                         'Sharhni ochish')

    def test_no_link_means_no_button_and_untouched_text(self):
        text = 'a\nb\n<a href="https://elsewhere/">c</a>'
        params = events.message_for(order(text=text, url=''))
        self.assertNotIn('reply_markup', params)
        self.assertEqual(params['text'], text)

    def test_only_an_exact_trailing_anchor_is_dropped(self):
        # A different link on the last line stays; so does the link when it is not last.
        text = f'a\n<a href="{PANEL}">Buyurtmani ochish</a>\nIzoh: tez'
        self.assertEqual(events.message_for(order(text=text))['text'], text)
        text = 'a\n<a href="https://other/">x</a>'
        self.assertEqual(events.message_for(order(text=text))['text'], text)

    def test_unknown_event_and_empty_text_are_ignored(self):
        self.assertIsNone(events.message_for({'event': 'test.ping', 'text': 'sinov'}))
        self.assertIsNone(events.message_for({'event': 'order.paid', 'text': '  '}))
        self.assertIsNone(events.message_for({'event': 'order.paid'}))
        self.assertIsNone(events.message_for({}))

    def test_the_code_ceiling_is_shown_without_a_button(self):
        body = {'event': 'signin.ceiling', 'text': '<b>SMS-kodlar chegarasiga yetildi</b>',
                'data': {'signin': {'codes_sent': 150, 'window_minutes': 60}}}
        params = events.message_for(body)
        self.assertEqual(params['text'], body['text'])
        self.assertNotIn('reply_markup', params)

    def test_an_uzpost_status_opens_its_order(self):
        url = 'https://graphix.uz/uz/boshqaruv/buyurtmalar/GX-261018-0001/'
        body = {'event': 'uzpost.status',
                'text': '<b>Uzpost: joʻnatma holati</b> GX-261018-0001\n\n'
                        f'<a href="{url}">Buyurtmani ochish</a>',
                'data': {'shipment': {'order': 'GX-261018-0001', 'number': 'MM216886699UZ',
                                      'status': 'returned_to_origin', 'admin_url': url}}}
        params = events.message_for(body)
        self.assertEqual(params['text'], '<b>Uzpost: joʻnatma holati</b> GX-261018-0001')
        button = params['reply_markup']['inline_keyboard'][0][0]
        self.assertEqual(button, {'text': 'Buyurtmani ochish', 'url': url})

    def test_a_return_request_opens_the_request(self):
        url = 'https://graphix.uz/uz/boshqaruv/qaytarishlar/7/'
        body = {'event': 'return.new',
                'text': '<b>Yangi soʻrov: almashtirish</b> GX-261018-0001\n\n'
                        f'<a href="{url}">Soʻrovni ochish</a>',
                'data': {'return': {'id': 7, 'order': 'GX-261018-0001', 'kind': 'exchange',
                                    'reason': 'size', 'admin_url': url}}}
        params = events.message_for(body)
        self.assertEqual(params['text'], '<b>Yangi soʻrov: almashtirish</b> GX-261018-0001')
        button = params['reply_markup']['inline_keyboard'][0][0]
        self.assertEqual(button, {'text': 'Soʻrovni ochish', 'url': url})

    def test_non_http_link_gets_no_button(self):
        params = events.message_for(order(text='x', url='javascript:alert(1)'))
        self.assertNotIn('reply_markup', params)

    def test_malformed_data_does_not_raise(self):
        body = order(text='x')
        body['data'] = ['not', 'a', 'dict']
        self.assertNotIn('reply_markup', events.message_for(body))
        body['data'] = {'order': 'nope'}
        self.assertNotIn('reply_markup', events.message_for(body))


if __name__ == '__main__':
    unittest.main()
