from app.web.app import app

if __name__ == '__main__':
    # Increase default timeout for the development server
    app.run(debug=True, port=8080)
