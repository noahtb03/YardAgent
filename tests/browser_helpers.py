from pathlib import Path

ROOT = Path(__file__).parents[1]


def serve_ui(page):
    def route(request):
        from urllib.parse import urlparse
        path = urlparse(request.request.url).path
        file = ROOT / ('static/index.html' if path == '/' else 'static/view.html' if path == '/view' else path.lstrip('/'))
        if file.is_file() and file.resolve().is_relative_to(ROOT / 'static'):
            request.fulfill(path=str(file), content_type='text/javascript' if file.suffix == '.js' else 'text/html')
        else:
            request.fulfill(status=404, body='Not found')
    page.route('http://yard.test/**', route)


def saved_view(page, layout):
    serve_ui(page)
    page.route('**/model', lambda route: route.fulfill(json=dict(model_url=None, fallback=True, warnings=[])))
    page.route('**/render', lambda route: route.fulfill(status=503, json=dict(detail='Fixture render unavailable')))
    page.goto('http://yard.test/')
    page.evaluate('''async layout => {
      const { yardState } = await import('/static/storage.js');
      await yardState({layout, analysis: {}, budget: 1000});
    }''', layout)
    page.goto('http://yard.test/view')
    page.wait_for_selector('#source-totals')
