web: gunicorn config.wsgi:application --access-logfile - --error-logfile -
release: python manage.py migrate && python manage.py check --deploy --fail-level WARNING && python manage.py deployment_check && python manage.py data_audit --fail-on-warning
