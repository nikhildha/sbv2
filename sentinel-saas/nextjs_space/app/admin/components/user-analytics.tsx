'use client';

import { useState, useEffect } from 'react';
import {
    Users, UserPlus, Calendar, BarChart3,
    ArrowUp, ArrowDown, Activity, Star, Trash2, Edit3,
    Check, X, Search
} from 'lucide-react';

interface UserData {
    id: string;
    email: string;
    name: string;
    role: string;
    phone?: string;
    referralCode?: string;
    createdAt: string;
    subscription: { tier: string; status: string; coinScans: number } | null;
    _count: { bots: number; trades: number };
}

export default function UserAnalytics() {
    const [users, setUsers] = useState<UserData[]>([]);
    const [loading, setLoading] = useState(true);
    const [editingId, setEditingId] = useState<string | null>(null);
    const [editData, setEditData] = useState<any>({});
    const [search, setSearch] = useState('');
    const [deleteConfirm, setDeleteConfirm] = useState<string | null>(null);

    useEffect(() => { fetchUsers(); }, []);

    const fetchUsers = async () => {
        setLoading(true);
        try {
            const res = await fetch('/api/admin/users');
            if (res.ok) setUsers(await res.json());
        } catch (e) { console.error('Failed:', e); }
        setLoading(false);
    };

    const handleEdit = (user: UserData) => {
        setEditingId(user.id);
        setEditData({
            name: user.name || '',
            role: user.role,
            tier: user.subscription?.tier || 'free',
            status: user.subscription?.status || 'trial',
        });
    };

    const handleSave = async () => {
        if (!editingId) return;
        try {
            const res = await fetch('/api/admin/users', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ userId: editingId, ...editData }),
            });
            if (res.ok) { await fetchUsers(); setEditingId(null); }
        } catch (e) { console.error('Save failed:', e); }
    };

    const handleDelete = async (userId: string) => {
        try {
            const res = await fetch('/api/admin/users', {
                method: 'DELETE',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ userId }),
            });
            if (res.ok) { await fetchUsers(); setDeleteConfirm(null); }
        } catch (e) { console.error('Delete failed:', e); }
    };

    // Analytics
    const now = new Date();
    const today = users.filter(u => new Date(u.createdAt).toDateString() === now.toDateString());
    const thisWeek = users.filter(u => now.getTime() - new Date(u.createdAt).getTime() < 7 * 86400000);
    const paidUsers = users.filter(u => u.subscription && u.subscription.tier !== 'free');
    const conversionRate = users.length > 0 ? ((paidUsers.length / users.length) * 100).toFixed(1) : '0';

    const signupsByDay: { day: string; count: number }[] = [];
    for (let i = 6; i >= 0; i--) {
        const target = new Date(now); target.setDate(target.getDate() - i);
        const dayStr = target.toLocaleDateString('en-US', { weekday: 'short' });
        const count = users.filter(u => new Date(u.createdAt).toDateString() === target.toDateString()).length;
        signupsByDay.push({ day: dayStr, count });
    }
    const maxSignups = Math.max(...signupsByDay.map(d => d.count), 1);

    const tierDist = [
        { tier: 'Free', count: users.filter(u => !u.subscription || u.subscription.tier === 'free').length, color: 'bg-gray-400' },
        { tier: 'Pro', count: users.filter(u => u.subscription?.tier === 'pro').length, color: 'bg-amber-400' },
        { tier: 'Ultra', count: users.filter(u => u.subscription?.tier === 'ultra').length, color: 'bg-purple-400' },
    ];
    const totalForDist = Math.max(users.length, 1);

    const filteredUsers = search
        ? users.filter(u => u.email.toLowerCase().includes(search.toLowerCase()) || (u.name || '').toLowerCase().includes(search.toLowerCase()))
        : users;

    return (
        <div className="space-y-6">
            {/* Key Metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard icon={<Users className="w-5 h-5 text-blue-400" />} label="Total Users" value={users.length} change="+100%" positive />
                <MetricCard icon={<UserPlus className="w-5 h-5 text-green-400" />} label="New Today" value={today.length} change={`${thisWeek.length} this week`} positive />
                <MetricCard icon={<Star className="w-5 h-5 text-amber-400" />} label="Paid Users" value={paidUsers.length} change={`${conversionRate}% conversion`} positive={parseFloat(conversionRate) > 0} />
                <MetricCard icon={<Activity className="w-5 h-5 text-purple-400" />} label="Avg Trades/User" value={(users.reduce((s, u) => s + (u._count.trades || 0), 0) / Math.max(users.length, 1)).toFixed(1)} change="per user" positive />
            </div>

            {/* Charts Row */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                    <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                        <Calendar className="w-4 h-4 text-blue-400" /> Signups — Last 7 Days
                    </h3>
                    <div className="flex items-end justify-between gap-2 h-32">
                        {signupsByDay.map((d, i) => (
                            <div key={i} className="flex flex-col items-center flex-1 gap-1">
                                <span className="text-xs text-white font-mono">{d.count}</span>
                                <div className="w-full bg-gradient-to-t from-blue-600 to-blue-400 rounded-t-md transition-all" style={{ height: `${(d.count / maxSignups) * 100}%`, minHeight: d.count > 0 ? '8px' : '2px' }} />
                                <span className="text-xs text-gray-500">{d.day}</span>
                            </div>
                        ))}
                    </div>
                </div>
                <div className="bg-white/5 border border-white/10 rounded-xl p-6">
                    <h3 className="text-white font-semibold mb-4 flex items-center gap-2">
                        <BarChart3 className="w-4 h-4 text-purple-400" /> Plan Distribution
                    </h3>
                    <div className="space-y-4">
                        {tierDist.map((t) => (
                            <div key={t.tier}>
                                <div className="flex justify-between items-center mb-1.5">
                                    <span className="text-gray-300 text-sm">{t.tier}</span>
                                    <span className="text-white font-medium text-sm">{t.count} ({((t.count / totalForDist) * 100).toFixed(0)}%)</span>
                                </div>
                                <div className="w-full bg-white/5 rounded-full h-2.5 overflow-hidden">
                                    <div className={`${t.color} h-full rounded-full transition-all duration-700`} style={{ width: `${(t.count / totalForDist) * 100}%`, minWidth: t.count > 0 ? '4px' : '0' }} />
                                </div>
                            </div>
                        ))}
                    </div>
                    <div className="flex items-center justify-center mt-6 gap-6">
                        {tierDist.map((t) => (
                            <div key={t.tier} className="flex items-center gap-2">
                                <div className={`w-3 h-3 rounded-full ${t.color}`} />
                                <span className="text-gray-400 text-xs">{t.tier}</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>

            {/* ─── User Management Table ─────────────────────────────── */}
            <div className="bg-white/5 border border-white/10 rounded-xl overflow-hidden">
                <div className="px-6 py-4 border-b border-white/10 flex items-center justify-between">
                    <h3 className="text-white font-semibold flex items-center gap-2">
                        <Users className="w-4 h-4 text-cyan-400" /> User Management
                    </h3>
                    <div className="relative">
                        <Search className="w-4 h-4 text-gray-500 absolute left-3 top-1/2 -translate-y-1/2" />
                        <input
                            type="text" placeholder="Search users..."
                            value={search} onChange={(e) => setSearch(e.target.value)}
                            className="bg-white/5 border border-white/10 rounded-lg pl-9 pr-3 py-1.5 text-sm text-white placeholder-gray-500 outline-none focus:border-cyan-500/50 w-48"
                        />
                    </div>
                </div>

                <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="text-gray-400 text-xs uppercase border-b border-white/5">
                                <th className="px-4 py-3 text-left">User</th>
                                <th className="px-4 py-3 text-left">Role</th>
                                <th className="px-4 py-3 text-left">Plan</th>
                                <th className="px-4 py-3 text-left">Status</th>
                                <th className="px-4 py-3 text-center">Bots</th>
                                <th className="px-4 py-3 text-center">Trades</th>
                                <th className="px-4 py-3 text-left">Joined</th>
                                <th className="px-4 py-3 text-center">Actions</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-white/5">
                            {filteredUsers.map((user) => (
                                <tr key={user.id} className="hover:bg-white/[0.03] transition">
                                    <td className="px-4 py-3">
                                        {editingId === user.id ? (
                                            <input value={editData.name} onChange={(e) => setEditData({ ...editData, name: e.target.value })} className="bg-white/10 border border-cyan-500/50 rounded px-2 py-1 text-white text-sm w-32 outline-none" />
                                        ) : (
                                            <div>
                                                <p className="text-white font-medium">{user.name || '—'}</p>
                                                <p className="text-gray-500 text-xs">{user.email}</p>
                                            </div>
                                        )}
                                    </td>
                                    <td className="px-4 py-3">
                                        {editingId === user.id ? (
                                            <select value={editData.role} onChange={(e) => setEditData({ ...editData, role: e.target.value })} className="bg-white/10 border border-cyan-500/50 rounded px-2 py-1 text-white text-sm outline-none">
                                                <option value="user">user</option>
                                                <option value="admin">admin</option>
                                            </select>
                                        ) : (
                                            <span className={`px-2 py-0.5 rounded-full text-xs ${user.role === 'admin' ? 'bg-red-500/10 text-red-400' : 'bg-blue-500/10 text-blue-400'}`}>{user.role}</span>
                                        )}
                                    </td>
                                    <td className="px-4 py-3">
                                        {editingId === user.id ? (
                                            <select value={editData.tier} onChange={(e) => setEditData({ ...editData, tier: e.target.value })} className="bg-white/10 border border-cyan-500/50 rounded px-2 py-1 text-white text-sm outline-none">
                                                <option value="free">free</option>
                                                <option value="pro">pro</option>
                                                <option value="ultra">ultra</option>
                                            </select>
                                        ) : (
                                            <span className={`px-2 py-0.5 rounded-full text-xs ${user.subscription?.tier === 'ultra' ? 'bg-purple-500/10 text-purple-400' : user.subscription?.tier === 'pro' ? 'bg-amber-500/10 text-amber-400' : 'bg-gray-500/10 text-gray-400'}`}>
                                                {user.subscription?.tier || 'free'}
                                            </span>
                                        )}
                                    </td>
                                    <td className="px-4 py-3">
                                        {editingId === user.id ? (
                                            <select value={editData.status} onChange={(e) => setEditData({ ...editData, status: e.target.value })} className="bg-white/10 border border-cyan-500/50 rounded px-2 py-1 text-white text-sm outline-none">
                                                <option value="trial">trial</option>
                                                <option value="active">active</option>
                                                <option value="expired">expired</option>
                                                <option value="cancelled">cancelled</option>
                                            </select>
                                        ) : (
                                            <span className={`text-xs ${user.subscription?.status === 'active' ? 'text-green-400' : user.subscription?.status === 'trial' ? 'text-cyan-400' : 'text-gray-500'}`}>
                                                {user.subscription?.status || 'trial'}
                                            </span>
                                        )}
                                    </td>
                                    <td className="px-4 py-3 text-center text-white font-mono">{user._count.bots}</td>
                                    <td className="px-4 py-3 text-center text-white font-mono">{user._count.trades}</td>
                                    <td className="px-4 py-3 text-gray-400 text-xs">{new Date(user.createdAt).toLocaleDateString()}</td>
                                    <td className="px-4 py-3">
                                        <div className="flex items-center justify-center gap-2">
                                            {editingId === user.id ? (
                                                <>
                                                    <button onClick={handleSave} className="p-1.5 rounded-lg bg-green-500/10 text-green-400 hover:bg-green-500/20 transition" title="Save"><Check className="w-3.5 h-3.5" /></button>
                                                    <button onClick={() => setEditingId(null)} className="p-1.5 rounded-lg bg-gray-500/10 text-gray-400 hover:bg-gray-500/20 transition" title="Cancel"><X className="w-3.5 h-3.5" /></button>
                                                </>
                                            ) : deleteConfirm === user.id ? (
                                                <>
                                                    <button onClick={() => handleDelete(user.id)} className="p-1.5 rounded-lg bg-red-500/20 text-red-400 hover:bg-red-500/30 transition text-xs font-bold px-2">Confirm</button>
                                                    <button onClick={() => setDeleteConfirm(null)} className="p-1.5 rounded-lg bg-gray-500/10 text-gray-400 hover:bg-gray-500/20 transition" title="Cancel"><X className="w-3.5 h-3.5" /></button>
                                                </>
                                            ) : (
                                                <>
                                                    <button onClick={() => handleEdit(user)} className="p-1.5 rounded-lg bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20 transition" title="Edit"><Edit3 className="w-3.5 h-3.5" /></button>
                                                    <button onClick={() => setDeleteConfirm(user.id)} className="p-1.5 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20 transition" title="Delete"><Trash2 className="w-3.5 h-3.5" /></button>
                                                </>
                                            )}
                                        </div>
                                    </td>
                                </tr>
                            ))}
                            {filteredUsers.length === 0 && (
                                <tr><td colSpan={8} className="text-center py-8 text-gray-500">
                                    <Users className="w-8 h-8 mx-auto mb-2 opacity-30" />
                                    <p>{search ? 'No matching users' : 'No users found'}</p>
                                </td></tr>
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}

function MetricCard({ icon, label, value, change, positive }: {
    icon: React.ReactNode; label: string; value: string | number; change: string; positive: boolean;
}) {
    return (
        <div className="bg-white/5 border border-white/10 rounded-xl p-5">
            <div className="flex items-center justify-between mb-3">
                <span className="text-gray-400 text-sm">{label}</span>
                {icon}
            </div>
            <p className="text-2xl font-bold text-white">{value}</p>
            <div className="flex items-center gap-1 mt-1">
                {positive ? <ArrowUp className="w-3 h-3 text-green-400" /> : <ArrowDown className="w-3 h-3 text-red-400" />}
                <span className={`text-xs ${positive ? 'text-green-400' : 'text-red-400'}`}>{change}</span>
            </div>
        </div>
    );
}
