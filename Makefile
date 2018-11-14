build:
	docker-compose build

clean:
	docker-compose down

# Services

redis:
	docker-compose up -d redis

redis-client:
	docker-compose run --service-ports redis-client redis-cli -h redis -p 6379


.PHONY: build clean
.PHONY: redis redis-client
