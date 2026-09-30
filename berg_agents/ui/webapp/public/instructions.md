Extract this package in <web site>/public/. If your site is http://www.example.com, you should be able to access a file named http://www.example.com/public/favicon.ico.
Insert the following code in the <head> section of your pages:

```
<link rel="icon" type="image/png" href="/public/favicon-96x96.png" sizes="96x96" />
<link rel="icon" type="image/svg+xml" href="/public/favicon.svg" />
<link rel="shortcut icon" href="/public/favicon.ico" />
<link rel="apple-touch-icon" sizes="180x180" href="/public/apple-touch-icon.png" />
<link rel="manifest" href="/public/site.webmanifest" />
```

Make sure your favicon is properly setup:

https://example.com

Check https://realfavicongenerator.net/logo-maker/your-favicon-is-ready or if your web site runs locally, run npx realfavicon check <port>
