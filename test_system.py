#!/usr/bin/env python3
"""
System test script
Tests message sending to contact and group
"""

import time
import requests
from scheduler_core import MessageScheduler

DRIVER_URL = "http://127.0.0.1:5002"
TEST_CONTACT = "+1 555 123 4567"  # You
TEST_GROUP = "Test"  # Test group

def wait_for_driver():
    """Wait for driver to be ready"""
    print("Waiting for driver server...")
    for i in range(30):
        try:
            r = requests.get(f"{DRIVER_URL}/status", timeout=2)
            if r.status_code == 200 and r.json().get('ready'):
                print("✓ Driver ready!")
                return True
        except Exception:
            pass
        time.sleep(2)
        print(f"  Attempt {i+1}/30...")
    
    print("✗ Driver not ready")
    return False

def test_group_resolution():
    """Test group name resolution"""
    print("\n=== Testing Group Resolution ===")
    try:
        r = requests.get(f"{DRIVER_URL}/get_groups", timeout=5)
        if r.status_code == 200:
            groups = r.json().get('groups', [])
            print(f"Found {len(groups)} groups:")
            for g in groups:
                print(f"  - {g['name']} => {g['id']}")
                if g['name'].lower() == TEST_GROUP.lower():
                    print(f"✓ Found test group: {g['id']}")
                    return g['id']
        else:
            print(f"✗ Failed to fetch groups: {r.text}")
    except Exception as e:
        print(f"✗ Error: {e}")
    return None

def test_send_message():
    """Test sending message to contact"""
    print(f"\n=== Testing Message to {TEST_CONTACT} ===")
    scheduler = MessageScheduler("schedules/schedule.json")
    
    message = f"Test message from WhatsApp Scheduler - {time.strftime('%H:%M:%S')}"
    success, error_detail = scheduler.send_message_via_api(TEST_CONTACT, message)
    
    if success:
        print("✓ Message sent successfully!")
    else:
        print(f"✗ Message failed: {error_detail}")
    
    return success

def test_send_group_message(group_jid):
    """Test sending message to group"""
    print(f"\n=== Testing Message to Group ({TEST_GROUP}) ===")
    scheduler = MessageScheduler("schedules/schedule.json")
    
    message = f"Test group message from WhatsApp Scheduler - {time.strftime('%H:%M:%S')}"
    success, error_detail = scheduler.send_message_via_api(group_jid, message)
    
    if success:
        print("✓ Group message sent successfully!")
    else:
        print(f"✗ Group message failed: {error_detail}")
    
    return success

def test_send_poll(group_jid):
    """Test sending poll to group"""
    print(f"\n=== Testing Poll to Group ({TEST_GROUP}) ===")
    scheduler = MessageScheduler("schedules/schedule.json")
    
    question = "Which option do you prefer?"
    options = ["Option A", "Option B", "Option C"]
    success, error_detail = scheduler.send_poll_via_api(group_jid, question, options)
    
    if success:
        print("✓ Poll sent successfully!")
    else:
        print(f"✗ Poll failed: {error_detail}")
    
    return success

def test_schedule_system():
    """Test schedule creation and processing"""
    print("\n=== Testing Schedule System ===")
    scheduler = MessageScheduler("schedules/schedule.json")
    
    # Add a test schedule
    current_time = time.strftime("%H:%M")
    scheduler.add_message_schedule(
        TEST_CONTACT,
        "Test scheduled message",
        current_time,
        None
    )
    print(f"✓ Added test schedule for {current_time}")
    
    # Check pending schedules
    pending = scheduler.get_pending_schedules()
    print(f"Found {len(pending)} pending schedules")
    
    if pending:
        idx, sched = pending[0]
        print(f"  Schedule {idx}: {sched['contact']} at {sched['time']}")
        
        # Test marking as completed
        scheduler.mark_completed(idx, True)
        print("✓ Marked schedule as completed")
        
        # Verify status changed
        schedules = scheduler.load_schedules()
        if schedules[idx]['status'] == 'completed':
            print("✓ Status correctly updated to 'completed'")
        else:
            print(f"✗ Status is '{schedules[idx]['status']}', expected 'completed'")
    
    return True

def test_recurring_schedule():
    """Test recurring schedule logic"""
    print("\n=== Testing Recurring Schedule ===")
    scheduler = MessageScheduler("schedules/schedule.json")
    
    # Add a daily recurring schedule
    current_time = time.strftime("%H:%M")
    scheduler.add_message_schedule(
        TEST_CONTACT,
        "Test recurring message",
        current_time,
        "daily"
    )
    print(f"✓ Added daily recurring schedule for {current_time}")
    
    # Get initial count
    schedules_before = scheduler.load_schedules()
    count_before = len(schedules_before)
    
    # Get the pending schedule
    pending = scheduler.get_pending_schedules()
    if pending:
        idx, sched = pending[0]
        print(f"  Found recurring schedule at index {idx}")
        
        # Mark as completed (should create next occurrence)
        scheduler.mark_completed(idx, True)
        print("✓ Marked recurring schedule as completed")
        
        # Check if new schedule was created
        schedules_after = scheduler.load_schedules()
        count_after = len(schedules_after)
        
        if count_after > count_before:
            print(f"✓ New occurrence created (count: {count_before} -> {count_after})")
            # Find the new schedule
            for s in schedules_after:
                if s.get('status') == 'pending' and s.get('recurring') == 'daily':
                    print(f"  New schedule time: {s['time']}")
                    break
        else:
            print("✗ New occurrence was not created")
    
    return True

def main():
    print("=== WhatsApp Scheduler System Test ===\n")
    
    # Wait for driver
    if not wait_for_driver():
        print("\n✗ Driver not ready, cannot proceed with tests")
        return
    
    time.sleep(2)
    
    # Test group resolution
    group_jid = test_group_resolution()
    
    time.sleep(2)
    
    # Test sending message to contact
    test_send_message()
    
    time.sleep(2)
    
    # Test sending message to group (if found)
    if group_jid:
        test_send_group_message(group_jid)
        time.sleep(2)
        test_send_poll(group_jid)
    else:
        print(f"\n⚠ Skipping group tests (group '{TEST_GROUP}' not found)")
    
    time.sleep(2)
    
    # Test schedule system
    test_schedule_system()
    
    time.sleep(2)
    
    # Test recurring schedule
    test_recurring_schedule()
    
    print("\n=== Test Complete ===")

if __name__ == "__main__":
    main()
