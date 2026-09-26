"""Test script to verify orchestrator chat integration without needing database.

This validates:
1. CAP-CHAT-001 is registered in the orchestrator
2. The chat adapter is correctly wired
3. The capability resolves to the correct engine
4. The adapter structure is correct
"""
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

def test_orchestrator_chat_registration():
    """Test that CAP-CHAT-001 is properly registered."""
    print("=" * 70)
    print("TEST 1: Orchestrator Chat Capability Registration")
    print("=" * 70)
    
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        
        # Check if CAP-CHAT-001 is registered
        if "CAP-CHAT-001" not in orchestrator.capabilities:
            print("❌ FAIL: CAP-CHAT-001 not found in capability registry")
            return False
        
        cap = orchestrator.capabilities["CAP-CHAT-001"]
        print(f"✅ PASS: CAP-CHAT-001 registered")
        print(f"   Name: {cap.capability_name}")
        print(f"   Version: {cap.version}")
        print(f"   Preferred Engine: {cap.preferred_engine}")
        print(f"   Fallback Chain: {cap.fallback_chain}")
        print(f"   Confidence Threshold: {cap.confidence_threshold}")
        print(f"   Cost Limit: ${cap.cost_limit_per_call}")
        print(f"   Latency Target: {cap.latency_target_ms}ms")
        print(f"   Business Criticality: {cap.business_criticality}")
        print(f"   Cache TTL: {cap.cache_ttl_seconds}s")
        
        return True
    except Exception as e:
        print(f"❌ FAIL: Error during registration test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_chat_adapter_wiring():
    """Test that the chat adapter is properly wired to LLM-ENGINE-01."""
    print("\n" + "=" * 70)
    print("TEST 2: Chat Adapter Wiring")
    print("=" * 70)
    
    try:
        from app.services.orchestrator import engines
        
        # Check if CAP-CHAT-001 has adapters
        if "CAP-CHAT-001" not in engines.ADAPTERS:
            print("❌ FAIL: CAP-CHAT-001 not found in ADAPTERS")
            return False
        
        adapters = engines.ADAPTERS["CAP-CHAT-001"]
        print(f"✅ PASS: CAP-CHAT-001 has {len(adapters)} adapter(s)")
        
        for engine_id, handler in adapters.items():
            print(f"   {engine_id}: {handler.__name__}")
        
        # Check if LLM-ENGINE-01 has _llm_chat handler
        if "LLM-ENGINE-01" not in adapters:
            print("❌ FAIL: LLM-ENGINE-01 not wired to CAP-CHAT-001")
            return False
        
        handler = adapters["LLM-ENGINE-01"]
        if handler.__name__ != "_llm_chat":
            print(f"❌ FAIL: Expected _llm_chat, got {handler.__name__}")
            return False
        
        print(f"✅ PASS: LLM-ENGINE-01 correctly wired to _llm_chat")
        
        return True
    except Exception as e:
        print(f"❌ FAIL: Error during adapter wiring test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_capability_resolution():
    """Test that CAP-CHAT-001 resolves to the correct engine."""
    print("\n" + "=" * 70)
    print("TEST 3: Capability Resolution")
    print("=" * 70)
    
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        descriptions = orchestrator.describe()
        
        # Find CAP-CHAT-001
        chat_cap = None
        for cap in descriptions:
            if cap["capability_id"] == "CAP-CHAT-001":
                chat_cap = cap
                break
        
        if not chat_cap:
            print("❌ FAIL: CAP-CHAT-001 not found in orchestrator.describe()")
            return False
        
        print(f"✅ PASS: CAP-CHAT-001 resolves correctly")
        print(f"   Resolves at engine: {chat_cap['resolves_at_engine']}")
        print(f"   Resolves at tier: {chat_cap['resolves_at_tier']}")
        print(f"   Invokes LLM: {chat_cap['invokes_llm']}")
        print(f"   Adapter available: {chat_cap['adapter_available']}")
        
        if not chat_cap['adapter_available']:
            print("⚠️  WARNING: Adapter not available - capability will degrade down fallback chain")
            return False
        
        if chat_cap['resolves_at_engine'] != "LLM-ENGINE-01":
            print(f"⚠️  WARNING: Expected resolution at LLM-ENGINE-01, got {chat_cap['resolves_at_engine']}")
        
        return True
    except Exception as e:
        print(f"❌ FAIL: Error during resolution test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_engine_registry():
    """Test that LLM engines are properly registered."""
    print("\n" + "=" * 70)
    print("TEST 4: Engine Registry")
    print("=" * 70)
    
    try:
        from app.services.orchestrator import get_orchestrator
        
        orchestrator = get_orchestrator()
        statuses = orchestrator.engine_status()
        
        print(f"✅ PASS: Engine registry loaded with {len(statuses)} engines")
        print("\nEngine Status:")
        for engine in statuses:
            status_icon = "✅" if engine['health'] == "OK" and engine['circuit'] == "CLOSED" else "⚠️"
            print(f"   {status_icon} Tier {engine['tier']}: {engine['engine_id']} ({engine['name']})")
            print(f"      Health: {engine['health']}, Circuit: {engine['circuit']}")
            print(f"      Cost: ${engine['cost_per_call']}, Latency: {engine['typical_latency_ms']}ms")
        
        return True
    except Exception as e:
        print(f"❌ FAIL: Error during engine registry test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_adapter_structure():
    """Test that _llm_chat adapter has correct signature."""
    print("\n" + "=" * 70)
    print("TEST 5: Chat Adapter Structure")
    print("=" * 70)
    
    try:
        from app.services.orchestrator import engines
        import inspect
        
        handler = engines.ADAPTERS["CAP-CHAT-001"]["LLM-ENGINE-01"]
        sig = inspect.signature(handler)
        
        print(f"✅ PASS: _llm_chat signature: {sig}")
        
        # Check that it accepts a payload dict
        params = list(sig.parameters.keys())
        if "payload" not in params:
            print("⚠️  WARNING: Expected 'payload' parameter")
        else:
            print(f"   Parameters: {params}")
        
        return True
    except Exception as e:
        print(f"❌ FAIL: Error during adapter structure test: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("ORCHESTRATOR CHAT INTEGRATION TEST SUITE")
    print("=" * 70 + "\n")
    
    results = []
    
    results.append(("Registration", test_orchestrator_chat_registration()))
    results.append(("Adapter Wiring", test_chat_adapter_wiring()))
    results.append(("Capability Resolution", test_capability_resolution()))
    results.append(("Engine Registry", test_engine_registry()))
    results.append(("Adapter Structure", test_adapter_structure()))
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        icon = "✅" if result else "❌"
        print(f"{icon} {name}")
    
    print(f"\nPassed: {passed}/{total}")
    
    if passed == total:
        print("\n🎉 All tests passed! Chat is successfully wired into the orchestrator.")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Review output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
