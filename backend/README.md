# Backend security configuration

The backend requires `DJANGO_SECRET_KEY` in the environment used to start it.
Provide a newly generated, high-entropy value through your local Compose
environment and deployment secret settings; never commit the value. The
previous signing key was committed, so rotate it before deploying these
changes. Rotation invalidates existing Django sessions and signed cookies.

`DJANGO_DEBUG` defaults to `false` and must remain false when `PRODUCTION=true`.
Set `PRODUCTION=true` only when serving the application over HTTPS; this enables
secure cookies and the cross-site cookie policy needed by the hosted frontend.
