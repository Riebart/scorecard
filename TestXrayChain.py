"""
Run unit tests against the Xray chain code without submitting to AwS.
"""

import os

os.environ["MOCK_XRAY"] = "TRUE"

import unittest
import XrayChain


class XrayChainTests(unittest.TestCase):
    def test_fork1(self):
        """
        Ensure that you can't fork() from a chain with no messages.
        """
        chain = XrayChain.Chain()
        exc = None
        try:
            child = chain.fork()
        except RuntimeError as exc:
            pass
        assert exc is not None

    def test_fork2(self):
        """
        Ensure that a fork has the right parent.
        """
        chain = XrayChain.Chain()
        segment_id = chain.log(0, 1, "RootEvent")
        child = chain.fork(True)
        assert child.parent_id == segment_id
        child = chain.fork(False)
        assert child.parent_id == segment_id


if __name__ == "__main__":
    unittest.main()