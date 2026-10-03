import uvicorn

if __name__ == '__main__':
    uvicorn.run('heretic_gateway.app:create_app', factory=True, host='127.0.0.1', port=8080,
                workers=1, access_log=False, log_level='warning')
