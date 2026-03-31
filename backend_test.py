#!/usr/bin/env python3

import requests
import sys
import json
import time
from datetime import datetime

class TradingBotAPITester:
    def __init__(self, base_url="https://dfg-analysis-engine.preview.emergentagent.com"):
        self.base_url = base_url
        self.api_url = f"{base_url}/api"
        self.tests_run = 0
        self.tests_passed = 0
        self.failed_tests = []

    def log_test(self, name, success, details=""):
        """Log test result"""
        self.tests_run += 1
        if success:
            self.tests_passed += 1
            print(f"✅ {name} - PASSED")
        else:
            print(f"❌ {name} - FAILED: {details}")
            self.failed_tests.append({"test": name, "error": details})

    def test_api_endpoint(self, name, method, endpoint, expected_status=200, data=None, timeout=30):
        """Test a single API endpoint"""
        url = f"{self.api_url}/{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        try:
            if method == 'GET':
                response = requests.get(url, headers=headers, timeout=timeout)
            elif method == 'POST':
                response = requests.post(url, json=data, headers=headers, timeout=timeout)
            elif method == 'PUT':
                response = requests.put(url, json=data, headers=headers, timeout=timeout)
            
            success = response.status_code == expected_status
            
            if success:
                try:
                    response_data = response.json()
                    self.log_test(name, True, f"Status: {response.status_code}")
                    return True, response_data
                except:
                    self.log_test(name, True, f"Status: {response.status_code} (No JSON)")
                    return True, {}
            else:
                error_msg = f"Expected {expected_status}, got {response.status_code}"
                try:
                    error_detail = response.json()
                    error_msg += f" - {error_detail}"
                except:
                    error_msg += f" - {response.text[:200]}"
                self.log_test(name, False, error_msg)
                return False, {}
                
        except requests.exceptions.Timeout:
            self.log_test(name, False, f"Request timeout after {timeout}s")
            return False, {}
        except Exception as e:
            self.log_test(name, False, f"Exception: {str(e)}")
            return False, {}

    def test_root_endpoint(self):
        """Test root API endpoint"""
        return self.test_api_endpoint("Root API", "GET", "")

    def test_bot_status(self):
        """Test bot status endpoint"""
        return self.test_api_endpoint("Bot Status", "GET", "bot/status")

    def test_bot_start(self):
        """Test bot start endpoint"""
        return self.test_api_endpoint("Bot Start", "POST", "bot/start")

    def test_bot_stop(self):
        """Test bot stop endpoint"""
        return self.test_api_endpoint("Bot Stop", "POST", "bot/stop")

    def test_get_config(self):
        """Test get bot configuration"""
        return self.test_api_endpoint("Get Config", "GET", "bot/config")

    def test_update_config(self):
        """Test update bot configuration"""
        config_data = {
            "rsi_oversold": 25,
            "rsi_overbought": 75,
            "min_confidence": 70
        }
        return self.test_api_endpoint("Update Config", "PUT", "bot/config", data=config_data)

    def test_get_signals(self):
        """Test get signals endpoint"""
        return self.test_api_endpoint("Get Signals", "GET", "signals?limit=10")

    def test_get_pending_signals(self):
        """Test get pending signals endpoint"""
        return self.test_api_endpoint("Get Pending Signals", "GET", "signals/pending")

    def test_get_pairs(self):
        """Test get pairs endpoint"""
        success, data = self.test_api_endpoint("Get Pairs", "GET", "pairs")
        if success and data:
            pairs = data.get('pairs', [])
            if len(pairs) == 35:
                print(f"   ✓ Correct number of pairs: {len(pairs)}")
            else:
                print(f"   ⚠ Expected 35 pairs, got {len(pairs)}")
        return success, data

    def test_get_stats(self):
        """Test get stats endpoint"""
        return self.test_api_endpoint("Get Stats", "GET", "stats")

    def test_telegram_messages(self):
        """Test get telegram messages endpoint"""
        return self.test_api_endpoint("Get Telegram Messages", "GET", "telegram-messages?limit=10")

    def test_telegram_test(self):
        """Test telegram test endpoint"""
        print("🔔 Testing Telegram integration...")
        success, data = self.test_api_endpoint("Test Telegram", "POST", "test-telegram")
        if success and data:
            if data.get('success'):
                print("   ✓ Telegram test message sent successfully")
            else:
                print("   ⚠ Telegram test failed - check token/chat_id")
        return success, data

    def test_analyze_now(self):
        """Test analyze now endpoint"""
        return self.test_api_endpoint("Analyze Now", "POST", "analyze-now")

    def run_comprehensive_test(self):
        """Run all tests"""
        print("🚀 Starting Trading Bot API Tests")
        print("=" * 50)
        
        # Test basic endpoints
        print("\n📡 Testing Basic Endpoints:")
        self.test_root_endpoint()
        self.test_bot_status()
        
        # Test bot control
        print("\n🤖 Testing Bot Control:")
        self.test_bot_start()
        time.sleep(2)  # Wait for bot to start
        self.test_bot_status()  # Check if running
        self.test_bot_stop()
        time.sleep(1)  # Wait for bot to stop
        
        # Test configuration
        print("\n⚙️ Testing Configuration:")
        self.test_get_config()
        self.test_update_config()
        
        # Test data endpoints
        print("\n📊 Testing Data Endpoints:")
        self.test_get_signals()
        self.test_get_pending_signals()
        self.test_get_pairs()
        self.test_get_stats()
        self.test_telegram_messages()
        
        # Test integrations
        print("\n🔗 Testing Integrations:")
        self.test_telegram_test()
        
        # Test analysis (requires bot to be running)
        print("\n🔍 Testing Analysis:")
        self.test_bot_start()  # Start bot for analysis test
        time.sleep(1)
        self.test_analyze_now()
        
        # Print summary
        print("\n" + "=" * 50)
        print("📋 TEST SUMMARY")
        print("=" * 50)
        print(f"Total Tests: {self.tests_run}")
        print(f"Passed: {self.tests_passed}")
        print(f"Failed: {len(self.failed_tests)}")
        print(f"Success Rate: {(self.tests_passed/self.tests_run)*100:.1f}%")
        
        if self.failed_tests:
            print("\n❌ Failed Tests:")
            for test in self.failed_tests:
                print(f"  - {test['test']}: {test['error']}")
        
        return self.tests_passed == self.tests_run

def main():
    """Main test function"""
    tester = TradingBotAPITester()
    
    try:
        success = tester.run_comprehensive_test()
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n⚠️ Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"\n💥 Unexpected error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())