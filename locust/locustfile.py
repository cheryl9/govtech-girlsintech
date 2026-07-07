from locust import HttpUser, task, between, events
import random
import string

def random_username():
    """Generate a random username so parallel users do not collide"""
    return "user_" + "".join(random.choices(string.ascii_lowercase, k = 8))

# Simulate a user who only hits the auth service
class AuthUser(HttpUser):
    wait_time = between(1,3)
    def on_start(self):
        """Runs once when each simulated user starts"""
        self.username = random_username()
        self.password = "123456"
        self.token = None

        self.client.post("/register", json = {
            "username": self.username,
            "password": self.password
        })

        response = self.client.post("/login", json = {
            "username": self.username,
            "password": self.password
        })
        if response.status_code == 200:
            self.token = response.json().get("token")
    
    def auth_headers(self):
        return {"Authorization": f"Bearer {self.token}"}
    
    @task(3) # weight 3 = this task runs 3x more often than weight 1
    def validate_token(self):
        """Most common auth operaton - validate a token"""
        if self.token: 
            self.client.get("/validate", headers = self.auth_headers())
    
    @task(1)
    def check_health(self):
        self.client.get("/health")

    @task(1)
    def relogin(self):
        """Occassionally relogin to simulate session refresh"""
        response = self.client.post("/login", json = {
            "username": self.username,
            "password": self.password
        })
        if response.status_code == 200:
            self.token = response.json().get("token")
        
    # Inventory user who creates and browses inventory items
    class InventoryUser(HttpUser):
        wait_time = between(1,3)

        host = "http://localhost:8002"

        def on_start(self):
            """Register and login via auth service, then use token for inventory"""
            self.username = random_username()
            self.password = "123456"
            self.token = None
            self.item_ids = []

            # Register via auth service
            import requests
            reg = requests.post("http://localhost:8001/register", json={
                "username": self.username,
                "password": self.password
            })

            # Login via auth service
            login = requests.post("http://localhost:8001/login", json={
                "username": self.username,
                "password": self.password
            })
            if login.status_code == 200:
                self.token = login.json().get("token")

        def auth_headers(self):
            return {"Authorization": f"Bearer {self.token}"}

        @task(2)
        def list_items(self):
            if self.token:
                self.client.get("/items", headers=self.auth_headers())

        @task(3)
        def create_item(self):
            if self.token:
                response = self.client.post("/items", json={
                    "name": f"item_{random.randint(1, 1000)}",
                    "quantity": random.randint(1, 100),
                    "price": round(random.uniform(1.0, 500.0), 2)
                }, headers=self.auth_headers())
                if response.status_code == 201:
                    self.item_ids.append(response.json().get("id"))

        @task(1)
        def get_item(self):
            if self.token and self.item_ids:
                item_id = random.choice(self.item_ids)
                self.client.get(f"/items/{item_id}", headers=self.auth_headers())

        @task(1)
        def check_health(self):
            self.client.get("/health")