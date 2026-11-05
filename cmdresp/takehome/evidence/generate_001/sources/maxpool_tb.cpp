#include "gen/maxpool.hpp"
#include <cstdint>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

struct Beat { uint32_t data; bool last; };
static Beat read_beat(std::istream& in) {
    uint64_t data;
    unsigned last;
    if (!(in >> std::hex >> data >> std::dec >> last) || data > 0xffffffffULL || last > 1)
        throw std::runtime_error("Invalid scenario beat");
    return {static_cast<uint32_t>(data), bool(last)};
}
static bool equal(streamutils::axi4s_word<32> a, Beat b) {
    return a.data.to_uint() == b.data && bool(a.last) == b.last;
}

int main(int argc, char** argv) {
    if (argc != 3) { std::cerr << "Usage: tb scenarios.txt evidence.json\n"; return 2; }
    std::ifstream src(argv[1]);
    std::ofstream report(argv[2]);
    if (!src || !report) { std::cerr << "Cannot open input/evidence file\n"; return 2; }
    unsigned count;
    src >> count;
    report << "{\n  \"activations\": [\n";
    unsigned failures = 0;
    for (unsigned idx = 0; idx < count; ++idx) {
        std::string name;
        unsigned nin, nout, consumed, exp_halted, exp_error;
        uint32_t exp_tx;
        if (!(src >> name >> nin >> nout >> consumed >> exp_halted >> exp_error >> exp_tx))
            throw std::runtime_error("Invalid scenario metadata");
        std::vector<Beat> inputs, expected;
        for (unsigned n = 0; n < nin; ++n) inputs.push_back(read_beat(src));
        for (unsigned n = 0; n < nout; ++n) expected.push_back(read_beat(src));

        hls::stream<streamutils::axi4s_word<32>> in("s_in"), out("m_out");
        for (Beat b : inputs) {
            streamutils::axi4s_word<32> word;
            word.data = b.data; word.last = b.last; word.keep = -1; word.strb = -1;
            in.write(word);
        }
        ap_uint<1> halted = 1;
        ap_uint<32> error = 0xdeadbeef, error_tx_id = 0xffffffff;
        maxpool(in, out, halted, error, error_tx_id);

        bool status_ok = halted == exp_halted && error == exp_error && error_tx_id == exp_tx;
        bool output_ok = true;
        unsigned got_out = 0;
        while (!out.empty()) {
            auto word = out.read();
            if (got_out >= expected.size() || !equal(word, expected[got_out])
                || word.keep != 15 || word.strb != 15) output_ok = false;
            ++got_out;
        }
        output_ok = output_ok && got_out == nout;
        bool suffix_ok = true;
        unsigned left = 0;
        while (!in.empty()) {
            auto word = in.read();
            if (consumed + left >= inputs.size() || !equal(word, inputs[consumed + left]))
                suffix_ok = false;
            ++left;
        }
        suffix_ok = suffix_ok && left == nin - consumed;
        bool ok = status_ok && output_ok && suffix_ok;
        failures += !ok;
        std::cout << "ACTIVATION " << idx << " " << name << " " << (ok ? "PASS" : "FAIL")
                  << " outputs=" << got_out << " consumed=" << nin - left
                  << " status=" << halted << "," << error << "," << error_tx_id << "\n";
        if (idx) report << ",\n";
        report << "    {\"index\":" << idx << ",\"name\":\"" << name
               << "\",\"pass\":" << (ok ? "true" : "false")
               << ",\"status_match\":" << (status_ok ? "true" : "false")
               << ",\"output_match\":" << (output_ok ? "true" : "false")
               << ",\"remaining_suffix_match\":" << (suffix_ok ? "true" : "false")
               << ",\"input_beats\":" << nin << ",\"consumed_beats\":" << nin - left
               << ",\"remaining_beats\":" << left << ",\"output_beats\":" << got_out
               << ",\"halted\":" << halted << ",\"error\":" << error
               << ",\"error_tx_id\":" << error_tx_id << "}";
    }
    report << "\n  ],\n  \"failures\": " << failures << "\n}\n";
    std::cout << "ALL_ACTIVATIONS " << count << " FAILURES " << failures << "\n";
    return failures ? 1 : 0;
}
