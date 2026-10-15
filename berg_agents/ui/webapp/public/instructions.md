Extract this package in <web site>/favicon/. If your site is http://www.example.com, you should be able to access a file
named http://www.example.com/favicon/favicon.ico.

Insert the following code in the <head> section of your pages:
```
<link rel="icon" type="image/png" href="/favicon/favicon-96x96.png?v=20261015" sizes="96x96" />
<link rel="icon" type="image/svg+xml" href="/favicon/favicon.svg?v=20261015" />
<link rel="shortcut icon" href="/favicon/favicon.ico?v=20261015" />
<link rel="apple-touch-icon" sizes="180x180" href="/favicon/apple-touch-icon.png?v=20261015" />
<meta name="apple-mobile-web-app-title" content="Berg-Agents" />
<link rel="manifest" href="/favicon/site.webmanifest?v=20261015" />
```


Make sure your favicon is properly setup:

https://example.com

Check https://realfavicongenerator.net/logo-maker/your-favicon-is-ready or if your web site runs locally, run npx
realfavicon check <port>
