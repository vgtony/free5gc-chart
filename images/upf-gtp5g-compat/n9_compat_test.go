package forwarder

import (
    "net"
    "testing"
    "github.com/free5gc/go-gtp5gnl"
    "github.com/wmnsk/go-pfcp/ie"
)

func TestLegacyN9AddressMatch(t *testing.T) {
    tests := []struct {name string; source uint8; tunnel bool; flags uint8; wantUE bool}{
        {"N9 downlink", ie.SrcInterfaceCore, true, 6, false},
        {"N3 uplink", ie.SrcInterfaceAccess, true, 2, true},
        {"anchor N6 downlink", ie.SrcInterfaceCore, false, 6, true},
        {"core source address", ie.SrcInterfaceCore, true, 2, true},
    }
    for _, tc := range tests { t.Run(tc.name, func(t *testing.T) {
        // Deliberately put the UE address before the direction and F-TEID.
        ies := []*ie.IE{ie.NewUEIPAddress(tc.flags, "10.61.0.1", "", 0, 0), ie.NewSourceInterface(tc.source)}
        if tc.tunnel { ies = append(ies, ie.NewFTEID(1, 13, net.ParseIP("10.160.101.204").To4(), nil, 0)) }
        attrs, err := (&Gtp5g{}).newPdi(ie.NewPDI(ies...))
        if err != nil { t.Fatal(err) }
        var hasUE, hasTunnel bool
        for _, attr := range attrs {
            if attr.Type == gtp5gnl.PDI_UE_ADDR_IPV4 { hasUE = true }
            if attr.Type == gtp5gnl.PDI_F_TEID { hasTunnel = true }
        }
        if hasUE != tc.wantUE || hasTunnel != tc.tunnel { t.Fatalf("UE=%v tunnel=%v", hasUE, hasTunnel) }
    }) }
}
